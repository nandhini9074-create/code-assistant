"""
app/modules/embedding/chunking/ast_chunker.py
AST-based chunker using Tree-sitter for intelligent code splitting.
"""

from __future__ import annotations

import tree_sitter

from app.core.logging import get_logger
from app.modules.embedding.chunking.text_chunker import chunk_text

logger = get_logger(__name__)


# Supported languages mapping for tree-sitter
# Note: Actual grammars need to be installed (e.g. tree-sitter-python)
SUPPORTED_LANGUAGES = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
}


def _get_language_parser(language: str) -> tree_sitter.Parser | None:
    """
    Attempt to load a Tree-sitter parser for the given language.
    Returns None if the language is unsupported or grammar is missing.
    """
    if language not in SUPPORTED_LANGUAGES:
        return None
        
    try:
        # In a real implementation, we would load the compiled language.so
        # or use the official language bindings like tree_sitter_python
        import importlib
        lang_module_name = f"tree_sitter_{SUPPORTED_LANGUAGES[language]}"
        lang_module = importlib.import_module(lang_module_name)
        
        parser = tree_sitter.Parser()
        # tree-sitter >= 0.22 style
        if hasattr(lang_module, "language"):
            parser.set_language(tree_sitter.Language(lang_module.language()))
        else:
            parser.set_language(tree_sitter.Language(lang_module.LANGUAGE, language))
        return parser
    except ImportError:
        logger.debug("tree_sitter_lang_missing", language=language)
        return None
    except Exception as exc:
        logger.warning("tree_sitter_load_failed", language=language, exc_info=exc)
        return None


def _extract_nodes(
    node: tree_sitter.Node, 
    content_bytes: bytes, 
    node_types: set[str],
) -> list[dict[str, str | int]]:
    """
    Recursively extract specific node types (e.g., classes, functions) from the AST.
    """
    chunks = []
    
    # If this node is one we want to extract
    if node.type in node_types:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        # Extract the raw source code for this node
        raw_code = content_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        
        chunks.append({
            "content": raw_code,
            "start_line": start_line,
            "end_line": end_line,
            "type": node.type,
        })
        
        # We don't recurse into extracted nodes to avoid duplicating code in chunks.
        # (Though in some complex languages, nested functions might be desired).
        return chunks
        
    # Otherwise, search children
    for child in node.children:
        chunks.extend(_extract_nodes(child, content_bytes, node_types))
        
    return chunks


def chunk_ast(
    content: str,
    language: str | None,
) -> list[dict[str, str | int]]:
    """
    Chunk code using Tree-sitter AST parsing.
    Falls back to plain text chunking if language is unsupported or parsing fails.
    
    Args:
        content: Raw source code string.
        language: Detected language (e.g. 'python').
        
    Returns:
        List of chunks containing content and metadata.
    """
    if not language:
        logger.debug("ast_chunker_fallback_to_text", reason="no_language_detected")
        return chunk_text(content)
        
    parser = _get_language_parser(language)
    if not parser:
        logger.debug("ast_chunker_fallback_to_text", reason="tree_sitter_parser_unavailable", language=language)
        return chunk_text(content)
        
    try:
        content_bytes = content.encode("utf-8")
        tree = parser.parse(content_bytes)
        
        target_nodes = {
            "function_definition", 
            "class_definition", 
            "method_definition",
            "function_declaration",
            "method_declaration",
            "class_declaration",
        }
        
        chunks = _extract_nodes(tree.root_node, content_bytes, target_nodes)
        
        # If we couldn't find any structural chunks, fallback to text
        if not chunks:
            logger.debug("ast_chunker_no_nodes_found_fallback_to_text", language=language)
            return chunk_text(content)
            
        logger.debug("ast_chunking_success", language=language, chunks_count=len(chunks))
        return chunks
        
    except Exception as exc:
        logger.warning("ast_chunking_failed_fallback_to_text", language=language, error=str(exc))
        return chunk_text(content)
