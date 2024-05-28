import hashlib
import dspy
import ijson
from pathlib import Path
from typing import List, Optional, Union

from loguru import logger
import chromadb
import chromadb.utils.embedding_functions as embedding_functions
from pydantic import BaseModel, ValidationError

from dspygen.utils.file_tools import data_dir

# Configure loguru logger
logger.add("chatgpt_chromadb_retriever.log", rotation="10 MB", level="ERROR")

def calculate_file_checksum(file_path: str) -> str:
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

class Author(BaseModel):
    role: str
    name: Optional[str] = None
    metadata: dict

class ContentPart(BaseModel):
    content_type: str
    parts: Optional[List[Union[str, dict]]] = None

class Message(BaseModel):
    id: str
    author: Author
    content: ContentPart
    status: str
    metadata: dict

class Data(BaseModel):
    id: str
    message: Optional[Message] = None
    parent: Optional[str] = None
    children: List[str]

class Conversation(BaseModel):
    title: str
    mapping: dict

default_embed_fn = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="llama3",
)

class ChatGPTChromaDBRetriever(dspy.Retrieve):
    def __init__(
        self,
        json_file_path: str = data_dir() / "chatgpt_logs" / "conversations.json",
        collection_name: str = "chatgpt",
        persist_directory: str = data_dir(),
        check_for_updates: bool = True,
        embed_fn=default_embed_fn,
        k=5,
    ):
        """Initialize the ChatGPTChromaDBRetriever."""
        super().__init__(k)
        self.json_file_path = json_file_path
        self.collection_name = collection_name
        self.k = k
        self.persist_directory = Path(persist_directory)
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        self.embedding_function = embed_fn
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
        )
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        if not check_for_updates:
            return

        self.current_checksum = calculate_file_checksum(json_file_path)
        self.last_processed_checksum = self._load_last_processed_checksum()

        if self.current_checksum != self.last_processed_checksum:
            logger.info("Detected changes in the conversation history, processing...")
            self._process_and_store_conversations()
            self._save_last_processed_checksum()

    def _load_last_processed_checksum(self) -> Optional[str]:
        checksum_file = self.persist_directory / "last_checksum.txt"
        try:
            return checksum_file.read_text().strip()
        except FileNotFoundError:
            return None

    def _save_last_processed_checksum(self):
        checksum_file = self.persist_directory / "last_checksum.txt"
        checksum_file.write_text(self.current_checksum)

    def _process_and_store_conversations(self):
        temp_code_directory = Path("data/temp_code")
        temp_code_directory.mkdir(parents=True, exist_ok=True)
        
        with open(self.json_file_path, "rb") as json_file:
            count = -1
            while True:
                try:
                    for conversation in ijson.items(json_file, "item"):
                        count += 1
                        print(f"Processing conversation #{count} {conversation['title']}")
                        temp_code_directory = Path(f"data/temp_code/{conversation['title']}")
                        temp_code_directory.mkdir(parents=True, exist_ok=True)
                        try:
                            validated_conversation = Conversation(**conversation)
                            for _, data in validated_conversation.mapping.items():
                                validated_data = Data(**data)

                                if validated_data.message and validated_data.message.content.parts:
                                    # Detect and process code snippets
                                    code_snippets, non_code_text = self._extract_code_and_text(validated_data.message.content.parts)

                                    if code_snippets:
                                        for snippet, description in zip(code_snippets, non_code_text):
                                            document_id = f"{validated_data.id}_{hashlib.md5(snippet.encode()).hexdigest()}"

                                            # Check if the document already exists
                                            search_results = self.collection.get(ids=[document_id])
                                            if len(search_results["ids"]) > 0:
                                                # Update existing document
                                                self.collection.update(
                                                    ids=[document_id],
                                                    documents=[snippet],
                                                    metadatas=[{"id": validated_data.id, "description": description}]
                                                )
                                                logger.debug(f"Updated document with ID: {document_id}")
                                            else:
                                                # Add new document
                                                self.collection.add(
                                                    documents=[snippet],
                                                    metadatas=[{"id": validated_data.id, "description": description}],
                                                    ids=[document_id],
                                                )
                                                logger.debug(f"Added document with ID: {document_id}")

                                            # Save to temp code directory
                                            file_path = temp_code_directory / f"{document_id}.py"
                                            if snippet and description:
                                                with file_path.open("w", encoding="utf-8") as file:
                                                    logger.debug(f" code description to {description}")
                                                    logger.debug(f" code snippet to {snippet}")
                                                    file.write(f"# {description}\n{snippet}")
                                                logger.debug(f"Saved code snippet to {file_path}")

                        except ValidationError as e:
                            logger.error(f"Validation error: {e}")
                    break
                except ijson.JSONError as e:
                    logger.error(f"JSON parsing error: {e}")
                    break

    def _extract_code_and_text(self, parts: List[Union[str, dict]]) -> (List[str], List[str]):
        code_snippets = []
        non_code_text = []
        is_code_block = False
        current_code = []
        current_text = []

        for part in parts:
            if isinstance(part, str):
                lines = part.split("\n")
                for line in lines:
                    if line.strip().startswith("```") and not is_code_block:
                        is_code_block = True
                        if current_text:
                            non_code_text.append(" ".join(current_text))
                            current_text = []
                        continue
                    elif line.strip().startswith("```") and is_code_block:
                        is_code_block = False
                        if current_code:
                            code_snippets.append("\n".join(current_code))
                            current_code = []
                        continue

                    if is_code_block:
                        current_code.append(line)
                    else:
                        current_text.append(line)

        if current_text:
            non_code_text.append(" ".join(current_text))

        return code_snippets, non_code_text

    def _update_collection_metadata(self):
        with open(self.json_file_path, "rb") as json_file:
            while True:
                try:
                    for conversation in ijson.items(json_file, "item"):
                        try:
                            validated_conversation = Conversation(**conversation)
                            for _, data in validated_conversation.mapping.items():
                                validated_data = Data(**data)

                                if validated_data.message and validated_data.message.content.parts:
                                    # Filter and process text parts only
                                    document_text = ' '.join(
                                        part for part in validated_data.message.content.parts if isinstance(part, str)
                                    )

                                    meta = {
                                        "id": validated_data.id,
                                        "role": validated_data.message.author.role,
                                        "title": validated_conversation.title
                                    }

                                    self.collection.update(metadatas=[meta], ids=[validated_data.id])
                                    logger.debug(f"Updated document with ID: {validated_data.id}")

                        except ValidationError as e:
                            logger.error(f"Validation error: {e}")
                    break
                except ijson.JSONError as e:
                    logger.error(f"JSON parsing error: {e}")
                    break

    def forward(
        self,
        query_or_queries: Union[str, List[str]],
        k: Optional[int] = None,
        contains: Optional[str] = None,
        role: str = "assistant",
    ) -> list[dict]:
        """Search with ChromaDB for top passages for the provided query/queries.

        Args:
            query_or_queries (Union[str, List[str]]): The query or queries to search for.
            k (Optional[int], optional): The number of top passages to retrieve. Defaults to None, which will use the value in self.k.
            contains (Optional[str], optional): The string that the retrieved passages must contain. Defaults to None.
            role: The role of the author of the message. Defaults to "assistant".

        Returns:
            list[dict]: A list of the retrieved passages.
        """

        queries = [query_or_queries] if isinstance(query_or_queries, str) else query_or_queries
        queries = [q for q in queries if q]

        if not queries:
            logger.error("No valid queries provided")
            return []

        try:
            embeddings = self.embedding_function(queries)
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            return []

        if not embeddings or not embeddings[0]:
            logger.error("No embeddings generated")
            return []

        k = self.k if k is None else k

        try:
            if contains is not None:
                results = self.collection.query(
                    query_embeddings=embeddings,
                    n_results=k,
                    where={"role": role},
                    where_document={"$contains": contains},
                )
            else:
                results = self.collection.query(
                    query_embeddings=embeddings,
                    where={"role": role},
                    n_results=k,
                )
        except Exception as e:
            logger.error(f"Error querying the collection: {e}")
            return []

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        # Combine documents and their corresponding metadata into a list of dictionaries
        return [{"code": doc, "description": meta.get("description", ""), "id": meta.get("id", "")}
                for doc, meta in zip(documents, metadatas)]

    def generate_powershell_script(self, code_files: List[str], directory_structure: str):
        script_lines = [
            "# PowerShell script to create directories and files",
            f'$baseDir = "{directory_structure}"',
            "",
            "# Define directories",
            "$directories = @(",
            '"$baseDir/src/dspygen/rm",',
            '"$baseDir/src/dspygen/utils",',
            '"$baseDir/src/dspygen/modules",',
            '"$baseDir/data/chatgpt_logs"',
            ")",
            "",
            "# Create directories",
            "foreach ($dir in $directories) {",
            "    if (-not (Test-Path -Path $dir)) {",
            "        New-Item -ItemType Directory -Path $dir -Force",
            "    }",
            "}",
            "",
            "# Create files",
            "$files = @(",
        ]

        for code_file in code_files:
            script_lines.append(f'"{code_file}",')

        script_lines += [
            ")",
            "",
            "foreach ($file in $files) {",
            "    if (-not (Test-Path -Path $file)) {",
            "        New-Item -ItemType File -Path $file -Force",
            "    }",
            "}",
            "",
            'Write-Host "Directories and files have been created successfully."',
        ]

        script_content = "\n".join(script_lines)
        script_path = Path("create_structure.ps1")
        script_path.write_text(script_content)
        logger.info(f"PowerShell script generated at {script_path}")

def main():
    retriever = ChatGPTChromaDBRetriever(check_for_updates=True)
    retriever._process_and_store_conversations() # use only for enforced overiding
    #retriever._update_collection_metadata()

    query = "Please provide the code to create a Tetris game in Python."
    matched_conversations = retriever.forward(query, k=5)

    code_files = []
    temp_code_directory = Path("data/temp_code")
    temp_code_directory.mkdir(parents=True, exist_ok=True)

    for i, conversation in enumerate(matched_conversations):
        logger.info(conversation)
        # Extract code and description from the conversation
        code = conversation.get('code', '')
        description = conversation.get('description', '')
        doc_id = conversation.get('id', '')

        # Save the code snippet to a file with the description as a comment
        code_file_path = temp_code_directory / f"{doc_id}_{i}.py"
        with code_file_path.open("w") as code_file:
            code_file.write(f"# {description}\n{code}")
        code_files.append(str(code_file_path))

    #directory_structure = "C:\\path\\to\\dspygen-composable-architecture"
    #retriever.generate_powershell_script(code_files, directory_structure)

if __name__ == "__main__":
    main()
