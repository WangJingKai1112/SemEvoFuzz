import os
import shutil
from pathlib import Path
from Utils.format_utils import remove_comments, format_code

def count_files(path: str) -> int:
    if not os.path.isdir(path):
        return 0
    files = os.listdir(path)
    count = 0
    for file in files:
        if os.path.isfile(Path(path) / file):
            count += 1
    return count

def count_folders(path: str) -> int:
    if not os.path.isdir(path):
        return 0
    folders = os.listdir(path)
    count = 0
    for folder in folders:
        if os.path.isdir(Path(path) / folder):
            count += 1
    return count

def read_file(path: str) -> str:
    if os.path.exists(path):
        with open(path, "r") as f:
            file = f.read()
        if path.suffix == ".c":
            file = remove_comments(file)
            file = format_code(file)
        return file
    return ""

def read_files(path: str) -> tuple:
    files = []
    count = count_files(path)
    for i in range(count):
        file_path = Path(path) / f"test_{i}.c"
        file = read_file(file_path)
        files.append(file)
    return files, count

def write_file(file: str, path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.suffix == ".c":
        file = remove_comments(file)
        file = format_code(file)
    with open(path, "w") as f:
        f.write(file)

def write_files(files: list, path: str, idx: list = []) -> None:
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    if len(idx) == 0:
        idx = list(range(len(files)))
    for i in idx:
        file_path = Path(path) / f"test_{i}.c"
        write_file(files[i], file_path)

def count_tokens(text: str, model: str = "gpt-4o-mini-2024-07-18") -> int:
    import tiktoken

    encoding = tiktoken.encoding_for_model(model)
    return len(encoding.encode(text))

def write_log(path: str, content: str) -> None:
    print(content)
    with open(path, "a") as f:
        f.write(content + "\n")
