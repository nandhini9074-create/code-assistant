"""
app/modules/embedding/chunking/ast_chunker.py
AST-based chunker using Tree-sitter for intelligent code splitting.
"""

from __future__ import annotations

import importlib
from typing import Any, TypedDict

import tree_sitter

from app.core.logging import get_logger
from app.modules.embedding.chunking.text_chunker import chunk_text
from app.shared.utils.file_utils import EXTENSION_TO_LANGUAGE

logger = get_logger(__name__)

# Default maximum chunk size in characters
DEFAULT_MAX_CHUNK_SIZE = 1500


class ASTChunk(TypedDict, total=False):
    """Standardized dictionary representation of a code chunk."""
    content: str
    start_line: int
    end_line: int
    type: str
    function_name: str | None
    class_name: str | None
    docstring: str | None
    metadata: dict[str, Any]


# Language alias normalization mapping
LANGUAGE_ALIASES: dict[str, str] = {
    "py": "python",
    "python": "python",
    "js": "javascript",
    "javascript": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "tsx": "typescript",
    "go": "go",
    "golang": "go",
    "rs": "rust",
    "rust": "rust",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "c++": "cpp",
}

# Module import names and loader functions for tree-sitter packages
SUPPORTED_LANGUAGES: dict[str, tuple[str, str]] = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
}

# Language-specific target AST node types for semantic code chunking
TARGET_NODE_TYPES: dict[str, set[str]] = {
    "python": {
        "function_definition",
        "class_definition",
        "decorated_definition",
    },
    "javascript": {
        "function_declaration",
        "method_definition",
        "class_declaration",
        "class_expression",
        "public_field_definition",
    },
    "typescript": {
        "function_declaration",
        "method_definition",
        "class_declaration",
        "class_expression",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "public_field_definition",
    },
    "go": {
        "function_declaration",
        "method_declaration",
        "type_declaration",
    },
    "rust": {
        "function_item",
        "impl_item",
        "trait_item",
        "struct_item",
        "enum_item",
    },
    "java": {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "method_declaration",
        "constructor_declaration",
    },
}


def normalize_language(language: str | None) -> str | None:
    """Normalize language string / alias to canonical name."""
    if not language:
        return None
    cleaned = language.strip().lower()
    if cleaned.startswith("."):
        return EXTENSION_TO_LANGUAGE.get(cleaned, cleaned.lstrip("."))
    return LANGUAGE_ALIASES.get(cleaned, cleaned)


def _get_language_parser(language: str) -> tree_sitter.Parser | None:
    """
    Attempt to load a Tree-sitter parser for the given language.
    Returns None if the language is unsupported or grammar package is missing.
    """
    norm_lang = normalize_language(language)
    if not norm_lang or norm_lang not in SUPPORTED_LANGUAGES:
        return None

    module_name, func_name = SUPPORTED_LANGUAGES[norm_lang]
    try:
        lang_module = importlib.import_module(module_name)
        lang_func = getattr(lang_module, func_name, None)
        if lang_func is None and hasattr(lang_module, "language"):
            lang_func = lang_module.language
        if lang_func is None:
            return None

        ts_lang = tree_sitter.Language(lang_func())
        return tree_sitter.Parser(ts_lang)
    except ImportError:
        logger.debug("tree_sitter_lang_missing", language=norm_lang)
        return None
    except Exception as exc:
        logger.warning("tree_sitter_load_failed", language=norm_lang, exc_info=exc)
        return None


def _has_significant_syntax_errors(root_node: tree_sitter.Node, threshold: int = 3) -> bool:
    """Check if the tree contains excessive ERROR or MISSING nodes."""
    error_count = 0

    def check_node(n: tree_sitter.Node) -> bool:
        nonlocal error_count
        if n.is_error or n.is_missing or n.type == "ERROR":
            error_count += 1
            if error_count >= threshold:
                return True
        for child in n.children:
            if check_node(child):
                return True
        return False

    return check_node(root_node)


def _extract_docstring(node: tree_sitter.Node, content_bytes: bytes, language: str) -> str | None:
    """Extract docstring or leading comment block if present."""
    if language == "python":
        body = node.child_by_field_name("body")
        if body and len(body.children) > 0:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement" and len(first_stmt.children) > 0:
                expr = first_stmt.children[0]
                if expr.type == "string":
                    raw = content_bytes[expr.start_byte:expr.end_byte].decode("utf-8", errors="replace")
                    return raw.strip('"""').strip("'''").strip('"').strip("'").strip()
    return None


def _extract_names(node: tree_sitter.Node, language: str, current_class: str | None) -> tuple[str | None, str | None]:
    """Extract (function_name, class_name) from an AST node."""
    node_type = node.type
    name_node = node.child_by_field_name("name")
    extracted_name = name_node.text.decode("utf-8", errors="replace") if name_node and name_node.text else None

    if language == "python":
        if node_type == "class_definition":
            return None, extracted_name
        elif node_type in ("function_definition", "decorated_definition"):
            if node_type == "decorated_definition":
                for child in node.children:
                    if child.type == "function_definition":
                        inner_name = child.child_by_field_name("name")
                        extracted_name = inner_name.text.decode("utf-8", errors="replace") if inner_name and inner_name.text else None
                        break
            return extracted_name, current_class

    elif language in ("javascript", "typescript"):
        if "class" in node_type or "interface" in node_type or "type_alias" in node_type or "enum" in node_type:
            return None, extracted_name
        return extracted_name, current_class

    elif language == "java":
        if "class" in node_type or "interface" in node_type or "enum" in node_type:
            return None, extracted_name
        return extracted_name, current_class

    elif language == "go":
        if node_type == "type_declaration":
            return None, extracted_name
        return extracted_name, current_class

    elif language == "rust":
        if node_type in ("struct_item", "enum_item", "trait_item"):
            return None, extracted_name
        elif node_type == "impl_item":
            type_node = node.child_by_field_name("type")
            impl_name = type_node.text.decode("utf-8", errors="replace") if type_node and type_node.text else None
            return None, impl_name
        return extracted_name, current_class

    return extracted_name, current_class


def _get_node_start_with_decorators(node: tree_sitter.Node) -> tuple[int, int]:
    """
    Finds the true start byte and line of a node by including preceding decorator siblings.
    In TypeScript/JavaScript, decorators are often siblings preceding the actual declaration.
    Returns (start_byte, start_line).
    """
    start_byte = node.start_byte
    start_line = node.start_point[0] + 1

    current = node.prev_sibling
    earliest_byte = start_byte
    earliest_line = start_line

    while current:
        if current.type == "decorator":
            earliest_byte = current.start_byte
            earliest_line = current.start_point[0] + 1
        elif current.type != "comment":
            break
        current = current.prev_sibling

    return earliest_byte, earliest_line


def _extract_nodes(
    node: tree_sitter.Node,
    content_bytes: bytes,
    target_nodes: set[str],
    language: str,
    current_class: str | None = None,
) -> list[ASTChunk]:
    """
    Recursively extract semantic nodes (methods, functions, classes, types).
    Implements a hierarchical non-overlapping chunk policy.
    """
    chunks: list[ASTChunk] = []
    node_type = node.type

    # Unpack decorated definition (e.g. @decorator in Python)
    effective_type = node_type
    inner_func_node = None
    if node_type == "decorated_definition":
        for child in node.children:
            if child.type in target_nodes:
                inner_func_node = child
                effective_type = child.type
                break
    elif node_type == "public_field_definition":
        effective_type = "property"

    is_class_like = any(keyword in effective_type for keyword in ("class", "interface", "struct", "impl", "type_declaration"))
    is_function_like = any(keyword in effective_type for keyword in ("function", "method", "constructor", "arrow"))

    if effective_type in target_nodes or node_type in target_nodes:
        func_name, cls_name = _extract_names(node, language, current_class)
        active_class = cls_name if is_class_like else current_class

        # Check if this class/container has inner methods/functions
        child_chunks: list[ASTChunk] = []
        body = node.child_by_field_name("body") or node
        for child in body.children:
            child_chunks.extend(_extract_nodes(child, content_bytes, target_nodes, language, current_class=active_class))

        if is_class_like and child_chunks:
            # Policy: Emit child methods as standalone semantic chunks.
            # Emit class header/structure chunk (first ~10 lines or docstring) to preserve class context without full duplication.
            start_byte, start_line = _get_node_start_with_decorators(node)
            first_child_line = child_chunks[0]["start_line"]
            header_end_line = min(node.end_point[0] + 1, max(start_line, first_child_line - 1))

            class_header_code = content_bytes[start_byte:body.start_byte].decode("utf-8", errors="replace").strip()
            if not class_header_code:
                class_header_code = content_bytes[start_byte:min(node.end_byte, start_byte + 300)].decode("utf-8", errors="replace")

            if class_header_code:
                header_chunk: ASTChunk = {
                    "content": class_header_code,
                    "start_line": start_line,
                    "end_line": header_end_line,
                    "type": effective_type,
                    "function_name": None,
                    "class_name": cls_name,
                    "docstring": _extract_docstring(node, content_bytes, language),
                    "metadata": {
                        "language": language,
                        "chunking_strategy": "ast",
                        "is_class_header": True,
                    },
                }
                chunks.append(header_chunk)

            chunks.extend(child_chunks)
            return chunks

        elif is_function_like and child_chunks:
            # Standalone or nested function: extract the full function as chunk
            # and omit redundant sub-nested chunks unless specifically standalone
            pass

        # Standalone function, method, or leaf class without sub-methods
        start_byte, start_line = _get_node_start_with_decorators(node)
        end_line = node.end_point[0] + 1
        raw_code = content_bytes[start_byte:node.end_byte].decode("utf-8", errors="replace")

        chunk: ASTChunk = {
            "content": raw_code,
            "start_line": start_line,
            "end_line": end_line,
            "type": effective_type,
            "function_name": func_name,
            "class_name": cls_name,
            "docstring": _extract_docstring(node, content_bytes, language),
            "metadata": {
                "language": language,
                "chunking_strategy": "ast",
            },
        }
        chunks.append(chunk)
        return chunks

    # If this node is not a target node, recurse into its children
    for child in node.children:
        chunks.extend(_extract_nodes(child, content_bytes, target_nodes, language, current_class=current_class))

    return chunks


def _split_oversized_chunk(chunk: ASTChunk, max_chunk_size: int) -> list[ASTChunk]:
    """Secondary splitting of an AST chunk that exceeds max_chunk_size."""
    raw_content = chunk["content"]
    if len(raw_content) <= max_chunk_size:
        return [chunk]

    sub_chunks = chunk_text(
        content=raw_content,
        max_chunk_size=max_chunk_size,
        overlap_size=min(150, max_chunk_size // 4),
        metadata={
            "language": chunk.get("metadata", {}).get("language"),
            "chunking_strategy": "ast_split",
        },
    )

    base_start_line = chunk["start_line"]
    result: list[ASTChunk] = []

    for sub in sub_chunks:
        sub_start = base_start_line + sub["start_line"] - 1
        sub_end = base_start_line + sub["end_line"] - 1
        split_chunk: ASTChunk = {
            "content": str(sub["content"]),
            "start_line": sub_start,
            "end_line": sub_end,
            "type": chunk["type"],
            "function_name": chunk.get("function_name"),
            "class_name": chunk.get("class_name"),
            "docstring": chunk.get("docstring"),
            "metadata": {
                **chunk.get("metadata", {}),
                "chunking_strategy": "ast_split",
            },
        }
        result.append(split_chunk)

    return result if result else [chunk]


def chunk_ast(
    content: str,
    language: str | None,
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
    file_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Chunk code using Tree-sitter AST parsing with language-aware grammars,
    syntax error handling, sub-splitting for oversized nodes, and fallback to text.

    Args:
        content: Raw source code string.
        language: Detected language name or file extension.
        max_chunk_size: Maximum characters per chunk (default 1500).
        file_path: Optional path to the file for logging context.

    Returns:
        List of chunks containing code content and metadata.
    """
    # 1. Handle empty / whitespace-only content
    if not content or not content.strip():
        return []

    norm_lang = normalize_language(language)

    # 2. If no language or unsupported, fallback to text chunker
    if not norm_lang:
        logger.debug("ast_chunker_fallback_to_text", reason="no_language_detected", file_path=file_path)
        return chunk_text(content, max_chunk_size=max_chunk_size, language="text")

    parser = _get_language_parser(norm_lang)
    if not parser:
        logger.debug(
            "ast_chunker_fallback_to_text",
            reason="tree_sitter_parser_unavailable",
            language=norm_lang,
            file_path=file_path,
        )
        return chunk_text(content, max_chunk_size=max_chunk_size, language=norm_lang)

    try:
        content_bytes = content.encode("utf-8")
        tree = parser.parse(content_bytes)

        # 3. Check for severe syntax errors in AST
        if _has_significant_syntax_errors(tree.root_node):
            logger.warning(
                "ast_chunker_syntax_errors_fallback_to_text",
                language=norm_lang,
                file_path=file_path,
            )
            return chunk_text(content, max_chunk_size=max_chunk_size, language=norm_lang)

        target_nodes = TARGET_NODE_TYPES.get(norm_lang, set())
        raw_chunks = _extract_nodes(tree.root_node, content_bytes, target_nodes, norm_lang)

        # 4. If no target semantic nodes found (e.g., constants/imports only), fallback to text chunking
        if not raw_chunks:
            logger.debug(
                "ast_chunker_no_nodes_found_fallback_to_text",
                language=norm_lang,
                file_path=file_path,
            )
            return chunk_text(content, max_chunk_size=max_chunk_size, language=norm_lang)

        # 5. Handle oversized chunks with secondary splitting
        processed_chunks: list[ASTChunk] = []
        for c in raw_chunks:
            processed_chunks.extend(_split_oversized_chunk(c, max_chunk_size))

        # 6. Sort deterministically by start_line, then end_line
        processed_chunks.sort(key=lambda x: (x["start_line"], x["end_line"]))

        logger.debug(
            "ast_chunking_success",
            language=norm_lang,
            chunks_count=len(processed_chunks),
            file_path=file_path,
        )
        return [dict(c) for c in processed_chunks]

    except Exception as exc:
        logger.warning(
            "ast_chunking_failed_fallback_to_text",
            language=norm_lang,
            file_path=file_path,
            error=str(exc),
        )
        return chunk_text(content, max_chunk_size=max_chunk_size, language=norm_lang)

