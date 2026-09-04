"""
app/modules/ingestion/pipeline/ast_chunking.py
Pipeline stage: AST Chunking.
"""

from app.core.logging import get_logger
from app.modules.embedding.chunking.ast_chunker import chunk_ast
from app.modules.ingestion.domain.ingestion_domain import ChunkRecord, IngestionContext
from app.shared.utils.file_utils import get_language_from_extension
from app.shared.utils.hashing import sha256_text

logger = get_logger(__name__)


class AstChunkingStage:
    async def execute(self, context: IngestionContext) -> None:
        """Chunks modified files into meaningful segments."""
        files_to_chunk = [f for f in context.files if f.is_new_or_modified and f.content]
        logger.info("stage_6_ast_chunking_started", files_to_chunk_count=len(files_to_chunk))
        total_chunks_created = 0

        for file in context.files:
            if not file.is_new_or_modified or not file.content:
                continue
                
            text = file.content.decode("utf-8", errors="ignore")
            language = get_language_from_extension(file.file_path)
            
            ast_chunks = chunk_ast(text, language)
            file_chunk_count = 0
            
            for chunk in ast_chunks:
                chunk_text = str(chunk.get("content", ""))
                if not chunk_text.strip():
                    continue
                    
                chunk_hash = sha256_text(chunk_text)
                file.chunks.append(
                    ChunkRecord(
                        file_path=file.file_path,
                        chunk_hash=chunk_hash,
                        chunk_type=str(chunk.get("type", "unknown")),
                        function_name=chunk.get("function_name") if "function_name" in chunk else None,
                        class_name=chunk.get("class_name") if "class_name" in chunk else None,
                        start_line=int(chunk.get("start_line", 1)),
                        end_line=int(chunk.get("end_line", 1)),
                        code=chunk_text,
                        docstring=chunk.get("docstring") if "docstring" in chunk else None,
                        metadata={}
                    )
                )
                file_chunk_count += 1
                total_chunks_created += 1

        logger.info("stage_6_ast_chunking_completed", total_chunks=total_chunks_created)
