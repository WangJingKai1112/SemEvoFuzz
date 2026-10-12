from tree_sitter import Language, Parser
import warnings
from pathlib import Path

warnings.simplefilter('ignore', FutureWarning) 
root = Path(__file__).resolve().parent.parent
Language.build_library(
    str(root / 'parser' / 'my-languages.so'),
    [str(root / 'tree-sitter-c')]
)
