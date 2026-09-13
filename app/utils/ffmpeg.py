import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional
from app.schemas.render import RenderSegment, SubtitleConfig

logger = logging.getLogger("FFmpegUtils")


def hex_to_ass_color(hex_str: str) -> str:
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 6:
        r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
        return f"&H00{b}{g}{r}&".upper()
    elif len(hex_str) == 8:
        a, r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6], hex_str[6:8]
        return f"&H{a}{b}{g}{r}&".upper()
    return "&H00FFFFFF&"


def format_ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def get_font_fallback(font_name: str) -> str:
    valid_fonts = ["Inter", "Roboto", "Arial", "DejaVu Sans", "Segoe UI", "Tahoma"]
    for vf in valid_fonts:
        if font_name.lower() in vf.lower():
            return vf
    return "Arial"


def split_into_phrases(text: str, max_chars: int) -> List[str]:
    """Cắt text thành các cụm từ không vượt quá max_chars, ưu tiên dấu câu."""
    words = text.strip().split()
    if not words:
        return []

    phrases = []
    current_phrase = []
    current_len = 0

    for word in words:
        if current_len + len(word) + 1 > max_chars and current_phrase:
            phrases.append(" ".join(current_phrase))
            current_phrase = [word]
            current_len = len(word)
        else:
            current_phrase.append(word)
            current_len += len(word) + 1

    if current_phrase:
        phrases.append(" ".join(current_phrase))

    return phrases


def split_long_segment(segment: RenderSegment, max_chars_per_frame: int) -> List[RenderSegment]:
    """Tự động chia nhỏ 1 segment dài thành nhiều segment ngắn theo tỉ lệ thời gian."""
    text = segment.text.strip()
    if len(text) <= max_chars_per_frame:
        return [segment]

    # Cắt các cụm hiển thị (mỗi cụm tối đa 2 dòng)
    phrases = split_into_phrases(text, max_chars_per_frame)
    if len(phrases) <= 1:
        return [segment]

    total_duration = max(0.1, segment.end - segment.start)
    total_chars = sum(len(p) for p in phrases)

    sub_segments = []
    current_start = segment.start

    for i, phrase in enumerate(phrases):
        phrase_ratio = len(phrase) / total_chars
        phrase_duration = total_duration * phrase_ratio
        current_end = current_start + phrase_duration if i < len(phrases) - 1 else segment.end

        sub_segments.append(
            RenderSegment(
                id=segment.id * 100 + i,
                start=round(current_start, 2),
                end=round(current_end, 2),
                source=segment.source,
                text=phrase
            )
        )
        current_start = current_end

    return sub_segments


def wrap_text_lines(text: str, max_chars_per_line: int, max_lines: int) -> str:
    """Tự bẻ dòng với giới hạn số dòng tối đa."""
    words = text.split()
    lines = []
    current_line = []
    current_len = 0

    for word in words:
        if current_len + len(word) + 1 > max_chars_per_line and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
        else:
            current_line.append(word)
            current_len += len(word) + 1

    if current_line:
        lines.append(" ".join(current_line))

    # Nếu vượt quá max_lines thì gộp các dòng cuối lại
    if len(lines) > max_lines:
        top_lines = lines[:max_lines - 1]
        remaining = " ".join(lines[max_lines - 1:])
        lines = top_lines + [remaining]

    return "\\N".join(lines)


def generate_ass_file(
    segments: List[RenderSegment],
    config: SubtitleConfig,
    width: int,
    height: int,
    output_path: Path
) -> Path:
    ass_color = hex_to_ass_color(config.color)
    font_name = get_font_fallback(config.font)
    bold_flag = "-1" if config.weight >= 600 else "0"

    # Scale font size chuẩn theo chiều ngắn nhất của video (base 360 mobile)
    base_dim = min(width, height)
    scale_factor = base_dim / 360.0
    scaled_font_size = max(18, int(config.fontSize * scale_factor * 1.15))
    scaled_outline = max(0.0, round(config.outline * scale_factor, 1))
    scaled_shadow = max(0.0, round(config.shadow * scale_factor, 1))

    pos_x = int((config.position.x / 100.0) * width)
    pos_y = int((config.position.y / 100.0) * height)

    ass_content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{scaled_font_size},{ass_color},&H000000FF,&H00000000,&H80000000,{bold_flag},0,0,0,100,100,0,0,1,{scaled_outline},{scaled_shadow},5,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]

    fade_tag = "\\fad(80,80)" if config.fadeInOut else ""
    max_chars_frame = config.maxCharsPerLine * config.maxLines

    # Xử lý cắt nhỏ câu dài trước khi ghi ASS
    final_segments: List[RenderSegment] = []
    for seg in sorted(segments, key=lambda s: s.start):
        if config.autoSplitLong:
            final_segments.extend(split_long_segment(seg, max_chars_frame))
        else:
            final_segments.append(seg)

    for seg in final_segments:
        start_time = format_ass_time(seg.start)
        end_time = format_ass_time(seg.end)
        wrapped_text = wrap_text_lines(seg.text.strip(), config.maxCharsPerLine, config.maxLines)
        dialogue = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{{\\an5\\pos({pos_x},{pos_y}){fade_tag}}}{wrapped_text}"
        ass_content.append(dialogue)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_content))

    return output_path


async def probe_video(video_path: Path) -> Dict[str, float]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path)
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=10 * 1024 * 1024
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFprobe failed: {stderr.decode('utf-8', errors='ignore')}")

    data = json.loads(stdout.decode("utf-8"))
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("Không tìm thấy video stream.")

    stream = streams[0]
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    duration = 0.0
    if "duration" in stream and stream["duration"] != "N/A":
        duration = float(stream["duration"])
    elif "format" in data and "duration" in data["format"]:
        duration = float(data["format"]["duration"])

    fps_str = stream.get("r_frame_rate", "30/1")
    try:
        num, den = map(int, fps_str.split("/"))
        fps = num / den if den != 0 else 30.0
    except Exception:
        fps = 30.0

    return {"width": width, "height": height, "duration": duration, "fps": fps}


async def run_ffmpeg_with_progress(
    cmd: List[str],
    duration: float,
    progress_callback: Optional[Callable[[int], Awaitable[None]]] = None
):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=10 * 1024 * 1024
    )

    out_time_regex = re.compile(r"out_time_us=(\d+)")
    stderr_chunks = []

    async def read_stdout():
        buffer = ""
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                match = out_time_regex.search(line)
                if match and duration > 0 and progress_callback:
                    us = int(match.group(1))
                    current_sec = us / 1_000_000.0
                    pct = int(min(99, max(0, (current_sec / duration) * 100)))
                    await progress_callback(pct)

    async def read_stderr():
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk.decode("utf-8", errors="ignore"))

    await asyncio.gather(read_stdout(), read_stderr())
    await proc.wait()

    if proc.returncode != 0:
        err_msg = "".join(stderr_chunks)[-2000:]
        logger.error(f"FFmpeg error: {err_msg}")
        raise RuntimeError(f"FFmpeg failed: {err_msg}")


async def extract_audio_from_video(video_path: Path, output_audio_path: Path) -> Path:
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "libmp3lame",
        "-ar", "16000", "-ac", "1", "-b:a", "64k",
        str(output_audio_path)
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=10 * 1024 * 1024
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction error: {stderr.decode('utf-8')}")
    return output_audio_path
