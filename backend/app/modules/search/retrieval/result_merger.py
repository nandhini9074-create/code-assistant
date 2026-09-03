"""
app/modules/search/retrieval/result_merger.py
Merges and deduplicates results from different search sources.
"""

from app.modules.search.domain.search_domain import RetrievedChunk


class ResultMerger:
    """Merges candidate lists."""
    
    def merge(self, dense_results: list[RetrievedChunk], sparse_results: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """
        Merge results, favoring higher scores or specific logic.
        Uses chunk_hash or file_path + line numbers as a deduplication key.
        """
        seen = {}
        
        # Add dense results first
        for chunk in dense_results:
            key = f"{chunk.file_path}:{chunk.chunk_hash}"
            seen[key] = chunk
            
        # Add sparse results, keeping the max score if duplicate
        for chunk in sparse_results:
            key = f"{chunk.file_path}:{chunk.chunk_hash}"
            if key in seen:
                # Naive combination: max score
                seen[key].score = max(seen[key].score, chunk.score)
            else:
                seen[key] = chunk
                
        return list(seen.values())
