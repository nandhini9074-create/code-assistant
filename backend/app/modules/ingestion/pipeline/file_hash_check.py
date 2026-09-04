"""
app/modules/ingestion/pipeline/file_hash_check.py
Pipeline stage: File hash check.
"""

from app.core.enums import FileStatus
from app.core.logging import get_logger
from app.infrastructure.database.models.file_hash import FileHash
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.file_hash_repo import FileHashRepository
from app.shared.utils.hashing import sha256_content

logger = get_logger(__name__)


class FileHashCheckStage:
    def __init__(self, registry_repo: FileHashRepository) -> None:
        self.registry_repo = registry_repo

    async def execute(self, context: IngestionContext) -> None:
        """Computes content hash and skips unchanged files."""
        logger.info("stage_5_hash_check_started", total_files=len(context.files), full_reindex=context.full_reindex)
        # Find active files in the repo to handle deletions
        active_files = await self.registry_repo.get_active_files(context.repo_id)
        active_paths = {f.file_path: f for f in active_files}
        
        seen_paths = set()
        new_modified_count = 0
        skipped_count = 0
        
        for file in context.files:
            if not file.content:
                file.is_new_or_modified = False
                skipped_count += 1
                continue
                
            file.file_hash = sha256_content(file.content)
            seen_paths.add(file.file_path)
            
            existing = active_paths.get(file.file_path)
            if existing and existing.file_hash == file.file_hash and not context.full_reindex:
                # File is unchanged and we are not doing a full reindex
                file.is_new_or_modified = False
                skipped_count += 1
            else:
                # File is new, modified, or a full reindex was requested
                file.is_new_or_modified = True
                new_modified_count += 1
                
            # Update registry (we do this per file for now, bulk is better in prod)
            if file.is_new_or_modified:
                registry_record = FileHash(
                    repo_id=context.repo_id,
                    file_path=file.file_path,
                    file_hash=file.file_hash,
                    blob_sha=file.blob_sha,
                    last_commit_sha=context.commit_sha,
                    status=FileStatus.ACTIVE.value,
                )
                await self.registry_repo.upsert_file(registry_record)
                
        # Any file in active_paths not in seen_paths was deleted
        for path in active_paths:
            if path not in seen_paths:
                context.deleted_files.append(path)

        logger.info(
            "stage_5_hash_check_completed",
            new_or_modified=new_modified_count,
            skipped=skipped_count,
            deleted_detected=len(context.deleted_files),
        )
