"""
app/modules/ingestion/pipeline/file_hash_check.py
Pipeline stage: File hash check.
"""

from app.core.enums import FileStatus
from app.infrastructure.database.models.file_registry import FileRegistry
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.file_registry_repo import FileRegistryRepository
from app.shared.utils.hashing import sha256_content


class FileHashCheckStage:
    def __init__(self, registry_repo: FileRegistryRepository) -> None:
        self.registry_repo = registry_repo

    async def execute(self, context: IngestionContext) -> None:
        """Computes content hash and skips unchanged files."""
        # Find active files in the repo to handle deletions
        active_files = await self.registry_repo.get_active_files(context.repo_id)
        active_paths = {f.file_path: f for f in active_files}
        
        seen_paths = set()
        
        for file in context.files:
            if not file.content:
                file.is_new_or_modified = False
                continue
                
            file.file_hash = sha256_content(file.content)
            seen_paths.add(file.file_path)
            
            existing = active_paths.get(file.file_path)
            if existing and existing.file_hash == file.file_hash:
                # File is unchanged
                file.is_new_or_modified = False
            else:
                # File is new or modified
                file.is_new_or_modified = True
                
            # Update registry (we do this per file for now, bulk is better in prod)
            if file.is_new_or_modified:
                registry_record = FileRegistry(
                    repo_id=context.repo_id,
                    file_path=file.file_path,
                    file_hash=file.file_hash,
                    blob_sha=file.blob_sha,
                    commit_sha=context.commit_sha,
                    status=FileStatus.ACTIVE.value,
                )
                await self.registry_repo.upsert_file(registry_record)
                
        # Any file in active_paths not in seen_paths was deleted
        for path in active_paths:
            if path not in seen_paths:
                context.deleted_files.append(path)
