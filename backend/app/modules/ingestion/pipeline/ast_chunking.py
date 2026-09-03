"""
app/modules/ingestion/pipeline/ast_chunking.py
Pipeline stage: AST Chunking.
"""

from app.modules.embedding.chunking.ast_chunker import chunk_ast
from app.modules.ingestion.domain.ingestion_domain import ChunkRecord, IngestionContext
from app.shared.utils.file_utils import get_language_from_extension
from app.shared.utils.hashing import sha256_text


class AstChunkingStage:
    async def execute(self, context: IngestionContext) -> None:
        """Chunks modified files into meaningful segments."""
        for file in context.files:
            if not file.is_new_or_modified or not file.content:
                continue
                
            text = file.content.decode("utf-8", errors="ignore")
            language = get_language_from_extension(file.file_path)
            
            ast_chunks = chunk_ast(text, language)
            
            for chunk in ast_chunks:
                chunk_text = str(chunk.get("content", ""))
                if not chunk_text.strip():
                    continue
                    
                chunk_hash = sha256_text(chunk_text)
                file.chunks.append(
                    ChunkRecord(
                        file_path=file.file_path,
                        chunk_hash=chunk_hash,
                        content=chunk_text,
                        metadata={
                            "start_line": chunk.get("start_line", 1),
                            "end_line": chunk.get("end_line", 1),
                            "type": chunk.get("type", "unknown"),
                        }
                    )
                )
