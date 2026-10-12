from typing import List
from pydantic import BaseModel

class extractLogFormat(BaseModel):
    log: str

def extract_log_prompt(log: str, target_file: str = "test_llm.c") -> str:
    user_message = (
        f"Extract the part related to {target_file} from the following log.\n"
        "Return the extracted log.\n"
        f"Log:\n{log}\n"
    )
    return user_message

class fixSuggestionsFormat(BaseModel):
    suggestions : List[str]

def fix_suggestions_prompt(code: str, log: str) -> str:
    user_message = (
        "You are an expert in C/C++ programming and debugging.\n"
        "Please analyze the bugs in the code based on the log STEP BY STEP. Ignore the warnings and focus on the errors.\n"
        "Return a list of specific and step-by-step suggestions to fix the bugs.\n"
        f"Code:\n```c\n{code}\n```\n"
        f"Log:\n{log}\n"
    )
    return user_message

class fixCodeFormat(BaseModel):
    fixed_code: str
def fix_code_prompt(code: str, suggestion: str) -> str:
    user_message = (
        "You are an expert in C/C++ programming and debugging.\n"
        "1. Fix the bugs in the code based on the fix suggestion.\n"
        "2. Remove ALL unused declaration statements.\n"
        "3. Returb the fixed code.\n"
        f"Code:\n```c\n{code}\n```\n"
        f"Fix Suggestion:\n{suggestion}\n"
    )
    return user_message
