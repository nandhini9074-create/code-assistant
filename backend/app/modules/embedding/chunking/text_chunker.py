"""
app/modules/embedding/chunking/text_chunker.py
Fallback line-based chunker for plain text or unsupported languages.
"""

from __future__ import annotations


def chunk_text(
    content: str,
    max_chunk_size: int = 1500,
    overlap_size: int = 150,
) -> list[dict[str, str | int]]:
    """
    Split text into chunks of lines, trying to respect max_chunk_size characters.
    
    Args:
        content: The raw text content.
        max_chunk_size: Maximum characters per chunk (approximate).
        overlap_size: Overlap characters between chunks.
        
    Returns:
        A list of dictionaries representing the chunks.
    """
    if not content.strip():
        return []

    lines = content.splitlines(keepends=True)
    chunks = []
    
    current_chunk_lines = []
    current_chunk_size = 0
    current_start_line = 1
    
    for i, line in enumerate(lines, 1):
        line_len = len(line)
        
        # If adding this line exceeds the max size and we already have content
        if current_chunk_size + line_len > max_chunk_size and current_chunk_lines:
            chunk_content = "".join(current_chunk_lines)
            chunks.append({
                "content": chunk_content,
                "start_line": current_start_line,
                "end_line": i - 1,
                "type": "text",
            })
            
            # Start new chunk with overlap if possible
            # Backtrack to find overlap lines
            overlap_lines = []
            overlap_len = 0
            for backtrack_line in reversed(current_chunk_lines):
                if overlap_len + len(backtrack_line) > overlap_size:
                    break
                overlap_lines.insert(0, backtrack_line)
                overlap_len += len(backtrack_line)
                
            current_chunk_lines = overlap_lines
            current_chunk_size = overlap_len
            current_start_line = i - len(overlap_lines)
            
        current_chunk_lines.append(line)
        current_chunk_size += line_len
        
    if current_chunk_lines:
        chunks.append({
            "content": "".join(current_chunk_lines),
            "start_line": current_start_line,
            "end_line": len(lines),
            "type": "text",
        })
        
    return chunks
