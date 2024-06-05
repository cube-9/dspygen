"""

"""
import dspy
from dspygen.utils.dspy_tools import init_dspy        

class SplitDealTerms(dspy.Signature):
    "split the deal_terms to the terms relevant for each month"

    deal_terms: str = dspy.InputField(desc="Deal terms to be split")
    invoice_period1: str = dspy.OutputField(desc="invoice period 1 terms")
    invoice_period2: str = dspy.OutputField(desc="invoice period 2 terms")
    invoice_period3: str = dspy.OutputField(desc="invoice period 3 terms")
    invoice_period4: str = dspy.OutputField(desc="invoice period 4 terms")
    invoice_period5: str = dspy.OutputField(desc="invoice period 5 terms")
    invoice_period6: str = dspy.OutputField(desc="invoice period 6 terms")
    invoice_period7: str = dspy.OutputField(desc="invoice period 7 terms")
    invoice_period8: str = dspy.OutputField(desc="invoice period 8 terms")
    invoice_period9: str = dspy.OutputField(desc="invoice period 9 terms")
    invoice_period10: str = dspy.OutputField(desc="invoice period 10 terms")
    invoice_period11: str = dspy.OutputField(desc="invoice period 11 terms")
    invoice_period12: str = dspy.OutputField(desc="invoice period 12 terms")


class DealTermSplitModule(dspy.Module):
    """DealTermSplitModule"""
    
    def __init__(self, **forward_args):
        super().__init__()
        self.forward_args = forward_args
        self.output = None
        
    def __or__(self, other):
        if other.output is None and self.output is None:
            self.forward(**self.forward_args)

        other.pipe(self.output)

        return other

    def forward(self, deal_terms):
        pred = dspy.ChainOfThought(SplitDealTerms)
        self.output = pred(deal_terms=deal_terms)
        return self.output
        
    def pipe(self, input_str):
        raise NotImplementedError("Please implement the pipe method for DSL support.")
        # Replace TODO with a keyword from you forward method
        # return self.forward(TODO=input_str)


from typer import Typer
app = Typer()


@app.command()
def call(deal_terms):
    """DealTermSplitModule"""
    init_dspy(model="gpt-4o", max_tokens=500)

    print(deal_term_split_call(deal_terms=deal_terms))



def deal_term_split_call(deal_terms):
    deal_term_split = DealTermSplitModule()
    return deal_term_split.forward(deal_terms=deal_terms)



def main():
    init_dspy()
    deal_terms = ""
    result = deal_term_split_call(deal_terms=deal_terms)
    print(result)



from fastapi import APIRouter
router = APIRouter()

@router.post("/deal_term_split/")
async def deal_term_split_route(data: dict):
    # Your code generation logic here
    init_dspy()

    print(data)
    return deal_term_split_call(**data)



"""
import streamlit as st


# Streamlit form and display
st.title("DealTermSplitModule Generator")
deal_terms = st.text_input("Enter deal_terms")

if st.button("Submit DealTermSplitModule"):
    init_dspy()

    result = deal_term_split_call(deal_terms=deal_terms)
    st.write(result)
"""

if __name__ == "__main__":
    main()
