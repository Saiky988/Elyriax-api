import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

from app.schemas.render import RenderConfig, RenderSegment
from app.services.job_manager import job_manager
from app.utils.ffmpeg import generate_ass_file, probe_video, run_ffmpeg_with_progress

logger = logging.getLogger("RenderService")


class RenderService:
    def __init__(self):
        concurrency = int(os.getenv("RENDER_CONCURRENCY", "1"))
        self._semaphore = asyncio.Semaphore(concurrency)

    async def process_job(
        self,
        job_id: str,
        job_dir: Path,
        video_path: Path,
        logo_path: Optional[Path],
        segments: List[RenderSegment],
        config: RenderConfig
    ):
        async with self._semaphore:
            try:
                await job_manager.update_progress(job_id, 5, "Analyzing video metadata...")
                meta = await probe_video(video_path)
                width, height, duration = int(meta["width"]), int(meta["height"]), meta["duration"]

                if width <= 0 or height <= 0:
                    raise ValueError("Không thể xác định kích thước video.")

                # 1. Tạo file ASS Subtitle
                await job_manager.update_progress(job_id, 15, "Generating subtitles style...")
                ass_path = job_dir / "subtitles.ass"
                generate_ass_file(segments, config.subtitle, width, height, ass_path)

                # 2. Xây dựng filter_complex
                filter_complex_parts = []
                current_v_stream = "0:v"

                # Khử sub gốc bằng Liquid Glass & Tán xạ ánh sáng (Light Diffusion)
                if config.blur.enabled and config.blur.strength > 0:
                    bx = int(max(0, min(width - 1, (config.blur.x / 100.0) * width)))
                    by = int(max(0, min(height - 1, (config.blur.y / 100.0) * height)))
                    bw = int(max(4, min(width - bx, (config.blur.width / 100.0) * width)))
                    bh = int(max(4, min(height - by, (config.blur.height / 100.0) * height)))

                    # Làm chẵn số pixel
                    bw = bw - (bw % 2)
                    bh = bh - (bh % 2)
                    blur_radius = max(2, int(config.blur.strength * 4))
                    rad = max(0, min(config.blur.borderRadius, min(bw, bh) // 2))

                    # Multi-pass boxblur làm mịn mượt mà
                    blur_chain = f"crop=w={bw}:h={bh}:x={bx}:y={by},boxblur={blur_radius}:{blur_radius}:2:2"

                    # Tán xạ quang học: Khuếch tán ánh sáng nền để hòa tan và xóa sạch vết chữ
                    diff_val = config.blur.lightDiffusion
                    if diff_val > 0:
                        brightness_boost = round(diff_val, 3)
                        contrast_boost = round(1.0 + (diff_val * 2.5), 3)
                        blur_chain += f",eq=brightness={brightness_boost}:contrast={contrast_boost}:saturation=1.12"

                    blur_chain += ",format=rgba"

                    # Mặt nạ biên mờ hình Sin + Bo tròn góc
                    if config.blur.liquidGlass:
                        if rad > 0:
                            alpha_expr = f"255*sin(PI*Y/H)*if(lte(abs(X-W/2),W/2-{rad})+lte(abs(Y-H/2),H/2-{rad}),1,if(lte(hypot(abs(X-W/2)-(W/2-{rad}),abs(Y-H/2)-(H/2-{rad})),{rad}),1,0))"
                        else:
                            alpha_expr = "255*sin(PI*Y/H)"
                    else:
                        if rad > 0:
                            alpha_expr = f"if(lte(abs(X-W/2),W/2-{rad})+lte(abs(Y-H/2),H/2-{rad}),255,if(lte(hypot(abs(X-W/2)-(W/2-{rad}),abs(Y-H/2)-(H/2-{rad})),{rad}),255,0))"
                        else:
                            alpha_expr = "255"

                    blur_chain += f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha_expr}'"

                    filter_complex_parts.append(
                        f"[{current_v_stream}]split=2[v_main][v_crop];"
                        f"[v_crop]{blur_chain}[v_liquid_glass];"
                        f"[v_main][v_liquid_glass]overlay=x={bx}:y={by}:format=auto[v_blurred]"
                    )
                    current_v_stream = "v_blurred"

                # Burn phụ đề ASS
                escaped_ass_path = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
                filter_complex_parts.append(
                    f"[{current_v_stream}]ass='{escaped_ass_path}'[v_sub]"
                )
                current_v_stream = "v_sub"

                # Overlay Logo nếu có
                has_logo = logo_path and logo_path.exists() and config.logo.enabled
                if has_logo:
                    logo_w = max(10, int((config.logo.size / 100.0) * width))
                    opacity_factor = max(0.0, min(1.0, config.logo.opacity / 100.0))
                    margin = config.logo.margin

                    pos_map = {
                        "top-left": f"x={margin}:y={margin}",
                        "top-right": f"x=main_w-overlay_w-{margin}:y={margin}",
                        "bottom-left": f"x={margin}:y=main_h-overlay_h-{margin}",
                        "bottom-right": f"x=main_w-overlay_w-{margin}:y=main_h-overlay_h-{margin}"
                    }
                    overlay_pos = pos_map.get(config.logo.position, pos_map["top-right"])

                    filter_complex_parts.append(
                        f"[1:v]scale={logo_w}:-1,format=rgba,colorchannelmixer=aa={opacity_factor}[logo_scaled];"
                        f"[{current_v_stream}][logo_scaled]overlay={overlay_pos}[v_final]"
                    )
                    current_v_stream = "v_final"

                final_filter_str = ";".join(filter_complex_parts)
                output_video_path = job_dir / "output.mp4"

                # 3. Lệnh FFmpeg
                cmd = [
                    "ffmpeg", "-y",
                    "-nostats",
                    "-progress", "pipe:1",
                    "-i", str(video_path)
                ]
                if has_logo:
                    cmd.extend(["-i", str(logo_path)])

                cmd.extend([
                    "-filter_complex", final_filter_str,
                    "-map", f"[{current_v_stream}]",
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "22",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(output_video_path)
                ])

                # 4. Thực thi Render
                await job_manager.update_progress(job_id, 20, "Rendering video with Frosted Glass effect...")

                async def progress_update(pct: int):
                    mapped_progress = int(20 + (pct * 0.78))
                    await job_manager.update_progress(job_id, mapped_progress, f"Rendering video ({pct}%)")

                await run_ffmpeg_with_progress(cmd, duration, progress_update)
                await job_manager.set_completed(job_id, str(output_video_path.resolve()))
                logger.info(f"Job {job_id} render completed successfully.")

            except Exception as e:
                logger.error(f"Render failed for job {job_id}: {str(e)}", exc_info=True)
                await job_manager.set_failed(job_id, f"Render error: {str(e)}")


render_service = RenderService()