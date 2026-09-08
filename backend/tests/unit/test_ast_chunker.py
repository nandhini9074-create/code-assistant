"""
tests/unit/test_ast_chunker.py
Unit tests for the Tree-sitter AST and fallback code chunker.
"""

from __future__ import annotations

import pytest

from app.modules.embedding.chunking.ast_chunker import chunk_ast
from app.modules.embedding.chunking.text_chunker import chunk_text


def test_empty_and_whitespace_content() -> None:
    assert chunk_ast("", "python") == []
    assert chunk_ast("   \n\t  \n", "python") == []
    assert chunk_text("") == []
    assert chunk_text("   \n\t  \n") == []


def test_python_ast_chunking() -> None:
    code = '''class UserService:
    """Service for user management."""
    def create_user(self, name: str) -> bool:
        """Create a user."""
        return True

def standalone_helper() -> int:
    return 42
'''
    chunks = chunk_ast(code, "python")
    assert len(chunks) >= 2

    func_chunk = next(c for c in chunks if c["function_name"] == "create_user")
    assert func_chunk["class_name"] == "UserService"
    assert func_chunk["docstring"] == "Create a user."
    assert func_chunk["start_line"] > 1

    helper_chunk = next(c for c in chunks if c["function_name"] == "standalone_helper")
    assert helper_chunk["class_name"] is None
    assert helper_chunk["metadata"]["chunking_strategy"] == "ast"


def test_javascript_ast_chunking() -> None:
    code = '''class UserService {
    createUser() {
        return true;
    }
}
function helper() {
    return 1;
}
'''
    chunks = chunk_ast(code, "javascript")
    assert len(chunks) >= 2
    method_chunk = next(c for c in chunks if c["function_name"] == "createUser")
    assert method_chunk["class_name"] == "UserService"

    func_chunk = next(c for c in chunks if c["function_name"] == "helper")
    assert func_chunk["class_name"] is None


def test_typescript_ast_chunking() -> None:
    code = '''interface UserDTO {
    id: string;
    name: string;
}

class AuthService {
    login(dto: UserDTO): boolean {
        return true;
    }
}
'''
    chunks = chunk_ast(code, "typescript")
    assert len(chunks) >= 2
    types = [c["type"] for c in chunks]
    assert any("interface" in t for t in types)
    assert any(c["function_name"] == "login" for c in chunks)


def test_java_ast_chunking() -> None:
    code = '''public class PaymentProcessor {
    public boolean processPayment(double amount) {
        return true;
    }
}
'''
    chunks = chunk_ast(code, "java")
    assert len(chunks) >= 1
    method_chunk = next(c for c in chunks if c["function_name"] == "processPayment")
    assert method_chunk["class_name"] == "PaymentProcessor"


def test_fallback_on_unsupported_language_or_no_nodes() -> None:
    code = 'import os\nCONFIG = 1\nVERSION = "1.0"\n'
    chunks = chunk_ast(code, "python")
    assert len(chunks) == 1
    assert chunks[0]["metadata"]["chunking_strategy"] == "text_fallback"
    assert chunks[0]["start_line"] == 1


def test_fallback_on_severe_syntax_error() -> None:
    err_code = "def (((( broken syntax {{{\n    return\n"
    chunks = chunk_ast(err_code, "python")
    assert len(chunks) >= 1
    assert chunks[0]["metadata"]["chunking_strategy"] == "text_fallback"


def test_huge_function_sub_splitting() -> None:
    huge_code = "def huge_function():\n" + "    x = 1\n" * 500
    chunks = chunk_ast(huge_code, "python", max_chunk_size=300)
    assert len(chunks) > 1
    for c in chunks:
        assert c["function_name"] == "huge_function"
        assert c["metadata"]["chunking_strategy"] == "ast_split"
        assert len(c["content"]) <= 350


def test_ts_decorated_property_preserves_decorator():
    code = """
class FileDto {
  @ForeignKey(() => Group)
  @Column({ allowNull: false })
  fileName: string;
}
"""
    chunks = chunk_ast(code, "typescript")
    prop_chunk = next(c for c in chunks if "fileName" in c.get("content", "") and c.get("function_name") == "fileName")
    assert "@ForeignKey(() => Group)" in prop_chunk["content"]
    assert "@Column({ allowNull: false })" in prop_chunk["content"]
    assert "fileName: string;" in prop_chunk["content"]


def test_ts_arrow_function_in_decorator_not_chunked_standalone():
    code = """
class FileDto {
  @ForeignKey(() => Group)
  fileName: string;
}
"""
    chunks = chunk_ast(code, "typescript")
    arrow_only = [c for c in chunks if c.get("content", "").strip() == "() => Group"]
    assert arrow_only == [], "Arrow function inside decorator must not be a standalone chunk"
