"""
app/modules/ingestion/pipeline/checkpoint_update.py
Pipeline stage: Checkpoint update.
"""

from app.core.enums import JobStatus, TriggerSource
from app.core.logging import get_logger
from app.modules.ingestion.domain.ingestion_domain import IngestionContext
from app.modules.ingestion.repository.ingestion_job_repo import IngestionJobRepository
from app.modules.repositories.repository.repository_repo import RepositoryRepository
from app.modules.webhooks.repository.webhook_event_repo import WebhookEventRepository

logger = get_logger(__name__)


class CheckpointUpdateStage:
    def __init__(
        self,
        job_repo: IngestionJobRepository,
        event_repo: WebhookEventRepository | None = None,
        repo_repo: RepositoryRepository | None = None,
    ) -> None:
        self.job_repo = job_repo
        self.event_repo = event_repo
        self.repo_repo = repo_repo

    async def execute(self, context: IngestionContext) -> None:
        """Updates job progress in database and writes commit SHA back to the repo record."""
        logger.info("stage_12_checkpoint_update_started", job_id=context.job_id)

        # Calculate progress
        failed_files_count = len(context.failed_files)
        successful_files_count = (
            sum(
                1
                for f in context.files
                if f.fetch_status == "success"
                or (hasattr(f.fetch_status, "value") and f.fetch_status.value == "success")
            )
            if context.files
            else 0
        )
        processed_chunks = sum(len(f.chunks) for f in context.files)

        # Determine status
        final_status = (
            JobStatus.PARTIAL
            if failed_files_count > 0 and successful_files_count > 0
            else (
                JobStatus.FAILED
                if failed_files_count > 0 and successful_files_count == 0
                else JobStatus.COMPLETED
            )
        )

        await self.job_repo.update_progress(
            context.job_id,
            processed_files=successful_files_count,
            processed_chunks=processed_chunks,
        )

        await self.job_repo.update_status(
            context.job_id,
            status=final_status,
            stage="pipeline_complete",
            commit_sha=context.commit_sha,
        )

        # ── Write commit SHA back to the repo record and trigger vulnerability scan ──
        # This switches status from "pending" → "active" and triggers the security scan
        # whenever a repository is newly ingested or its indexed commit has changed.
        is_zip = (
            context.source == TriggerSource.ZIP_UPLOAD
            or getattr(context.source, "value", None) == TriggerSource.ZIP_UPLOAD.value
            or str(context.source) == "zip_upload"
            or getattr(context, "extracted_zip_path", None) is not None
        )
        is_webhook = (
            context.source == TriggerSource.WEBHOOK
            or getattr(context.source, "value", None) == TriggerSource.WEBHOOK.value
            or str(context.source) == "webhook"
        )

        if (
            self.repo_repo is not None
            and context.repo_id
            and (context.commit_sha or is_zip)
            and final_status in (JobStatus.COMPLETED, JobStatus.PARTIAL)
        ):
            try:
                repo = await self.repo_repo.get_by_id(context.repo_id)
                previous_scanned_sha = getattr(repo, "vulnerability_scan_commit_sha", None) if repo else None
                previous_indexed_sha = getattr(repo, "last_indexed_commit_sha", None) if repo else None

                effective_commit_sha = context.commit_sha or previous_indexed_sha or f"zip_{str(context.repo_id)[:8]}"

                await self.repo_repo.update_commit_sha(context.repo_id, effective_commit_sha)
                logger.info(
                    "repo_commit_sha_updated",
                    repo_id=context.repo_id,
                    commit_sha=effective_commit_sha,
                    status=final_status.value,
                )

                # Determine whether to trigger the scan:
                # - For ZIP uploads: trigger scan on successful completion even when
                #   last_indexed_commit_sha is None (initial upload) or if commit SHA is new/changed.
                # - For GitHub webhooks: scan only when a valid new commit SHA differs from the previous SHA.
                # - For other sources (e.g. initial GitHub ingestion): trigger if new or changed commit SHA.
                if is_zip:
                    is_new_or_changed = (
                        previous_indexed_sha is None
                        or previous_scanned_sha is None
                        or effective_commit_sha != previous_scanned_sha
                    )
                elif is_webhook:
                    previous_sha = (
                        previous_scanned_sha
                        if previous_scanned_sha is not None
                        else previous_indexed_sha
                    )
                    is_new_or_changed = bool(
                        context.commit_sha
                        and (previous_sha is None or context.commit_sha != previous_sha)
                    )
                else:
                    is_new_or_changed = (
                        previous_scanned_sha is None
                        or context.commit_sha != previous_scanned_sha
                    )

                if is_new_or_changed:
                    logger.info(
                        "auto_triggering_vulnerability_scan",
                        repo_id=context.repo_id,
                        commit_sha=effective_commit_sha,
                        previous_scanned_sha=previous_scanned_sha,
                    )
                    from app.modules.code_analysis.vulnerability.scanner_service import (
                        run_repository_vulnerability_scan,
                    )
                    await run_repository_vulnerability_scan(
                        repo_id=str(context.repo_id),
                        commit_sha=effective_commit_sha,
                        qdrant_collection=repo.qdrant_collection if repo else None,
                    )
                else:
                    logger.info(
                        "skipping_vulnerability_scan_commit_unchanged",
                        repo_id=context.repo_id,
                        commit_sha=effective_commit_sha,
                        previous_scanned_sha=previous_scanned_sha,
                    )
            except Exception as exc:
                logger.error(
                    "repo_commit_sha_update_failed",
                    repo_id=context.repo_id,
                    commit_sha=context.commit_sha,
                    error=str(exc),
                )

        # Mark webhook event as processed
        if self.event_repo is not None and context.job_id:
            try:
                await self.event_repo.mark_processed_by_job_id(context.job_id)
            except Exception as exc:
                logger.warning(
                    "failed_to_mark_webhook_event_processed",
                    job_id=context.job_id,
                    error=str(exc),
                )

        logger.info(
            "stage_12_checkpoint_update_completed",
            job_id=context.job_id,
            processed_files=successful_files_count,
            failed_files=failed_files_count,
            processed_chunks=processed_chunks,
            status=final_status.value if hasattr(final_status, "value") else str(final_status),
        )
