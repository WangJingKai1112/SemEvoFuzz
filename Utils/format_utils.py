import re
import subprocess

def format_code(code: str) -> str:
    process = subprocess.Popen(
        ["clang-format"],
        stdout = subprocess.PIPE,
        stdin = subprocess.PIPE,
        stderr = subprocess.PIPE
    )
    stdout, stderr = process.communicate(input = code.encode())
    if process.returncode != 0:
        raise Exception(f"clang-format failed: {stderr.decode()}")
    return stdout.decode()

def replacer(match: re.Match) -> str:
    s = match.group(0)
    if s.startswith('/'):
        return " "
    else:
        return s

def remove_comments(code: str) -> str:
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    temp = []
    for x in re.sub(pattern, replacer, code).split('\n'):
        if x.strip() != "":
            temp.append(x)
    return '\n'.join(temp)