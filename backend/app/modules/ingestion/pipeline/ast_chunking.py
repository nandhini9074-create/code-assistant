"""
app/modules/ingestion/pipeline/ast_chunking.py
Pipeline stage: AST Chunking.
"""

from app.modules.ingestion.domain.ingestion_domain import ChunkRecord, IngestionContext
from app.shared.utils.hashing import sha256_text


class AstChunkingStage:
    async def execute(self, context: IngestionContext) -> None:
        """Chunks modified files into meaningful segments."""
        for file in context.files:
            if not file.is_new_or_modified or not file.content:
                continue
                
            # Simplified line-based chunker for the stub
            # In a real app, this uses tree-sitter to build AST chunks
            text = file.content.decode("utf-8", errors="ignore")
            lines = text.split("\n")
            
            # Very basic chunking (every 50 lines)
            chunk_size = 50
            for i in range(0, len(lines), chunk_size):
                chunk_text = "\n".join(lines[i:i + chunk_size])
                if not chunk_text.strip():
                    continue
                    
                chunk_hash = sha256_text(chunk_text)
                file.chunks.append(
                    ChunkRecord(
                        file_path=file.file_path,
                        chunk_hash=chunk_hash,
                        content=chunk_text,
                        metadata={
                            "start_line": i + 1,
                            "end_line": min(i + chunk_size, len(lines)),
                            "type": "module" # Stub
                        }
                    )
                )
