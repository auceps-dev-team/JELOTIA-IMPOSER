import argparse
import asyncio
import cProfile
import pstats
import shutil
import time
from pathlib import Path
from uuid import uuid4

import fitz
from PIL import Image

from src.core.models.domain import JobSettings
from src.core.processors.worker_pool import WorkerPoolManager
from src.utils.config import config


def generate_benchmark_files(count: int, input_dir: Path) -> list[Path]:
    print(f"Generating {count} benchmark files in {input_dir}...")
    paths = []
    base_pdf = input_dir / "base_bench.pdf"
    if not base_pdf.exists():
        doc = fitz.open()
        page = doc.new_page(width=100, height=100)
        page.draw_rect(fitz.Rect(10, 10, 90, 90), color=(0, 0, 1), fill=(1, 1, 0))
        doc.save(str(base_pdf))
        doc.close()

    base_img = input_dir / "base_bench.jpg"
    if not base_img.exists():
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(base_img)

    for i in range(count):
        target = input_dir / f"bench_file_{i}.pdf" if i % 2 == 0 else input_dir / f"bench_file_{i}.jpg"
        source = base_pdf if i % 2 == 0 else base_img
        shutil.copy(source, target)
        paths.append(target)
        
    return paths


async def run_benchmark(count: int, workers: int):
    # Setup temporary directories inside processing for bench
    bench_dir = config.processing_dir / "benchmark"
    input_dir = bench_dir / "input"
    output_dir = config.output_dir / "benchmark"
    
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Generation
    files = generate_benchmark_files(count, input_dir)
    
    settings = JobSettings(
        sheet_width_mm=1000.0,
        sheet_height_mm=1000.0,
        gap_mm=5.0,
        allow_rotation=True,
        export_format="PDF/X-1a"
    )
    
    pool = WorkerPoolManager(max_workers=workers)
    pool.start()
    
    # Split into jobs of 500 files to simulate realistic batches
    batch_size = 500
    batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]
    
    expected_jobs = len(batches)
    completed_jobs = 0
    completion_event = asyncio.Event()
    
    def on_job_completed(jid, result, error):
        nonlocal completed_jobs
        if error:
            print(f"Job {jid} failed: {error}")
        completed_jobs += 1
        if completed_jobs == expected_jobs:
            completion_event.set()
            
    pool.on_job_completed = on_job_completed
    
    print(f"Submitting {expected_jobs} jobs to pool with {workers} workers...")
    start_time = time.time()
    
    for batch in batches:
        await pool.submit_job(uuid4(), batch, settings)
        
    # Wait for completion (No timeout or large timeout)
    await completion_event.wait()
    
    end_time = time.time()
    total_time = end_time - start_time
    
    await pool.stop()
    
    print("-" * 50)
    print("Benchmark completed!")
    print(f"Total files processed : {count}")
    print(f"Total time            : {total_time:.2f} seconds")
    print(f"Throughput            : {(count / total_time):.2f} files/second")
    print("-" * 50)


def main():
    parser = argparse.ArgumentParser(description="Jelotia Imposer Benchmark Runner")
    parser.add_argument("--count", type=int, default=1000, help="Number of files to process")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers")
    parser.add_argument("--profile", action="store_true", help="Enable cProfile")
    args = parser.parse_args()

    if args.profile:
        print("Running with cProfile enabled...")
        profiler = cProfile.Profile()
        profiler.enable()
        
    asyncio.run(run_benchmark(args.count, args.workers))
    
    if args.profile:
        profiler.disable()
        stats = pstats.Stats(profiler).sort_stats('tottime')
        stats.print_stats(30)
        
        # Save profile
        profile_path = "benchmark_profile.prof"
        stats.dump_stats(profile_path)
        print(f"\nProfile saved to {profile_path}. Use 'snakeviz {profile_path}' to view.")


if __name__ == "__main__":
    main()
