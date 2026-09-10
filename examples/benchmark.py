import time
import numpy as np

def run_benchmark():
    print("Engram Alpha - AMX/BLAS Vector Similarity Benchmark")
    print("-" * 50)
    
    DIM = 384
    NUM_VECTORS = 1_500_000
    
    print(f"Generating {NUM_VECTORS} random {DIM}-dimensional vectors...")
    matrix = np.random.randn(NUM_VECTORS, DIM).astype(np.float32)
    query = np.random.randn(DIM).astype(np.float32)
    
    print("Normalizing vectors...")
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    query /= np.linalg.norm(query)
    
    print("Running optimized dot-product search...")
    start_time = time.perf_counter()
    scores = np.dot(matrix, query)
    top_indices = np.argpartition(scores, -5)[-5:]
    
    end_time = time.perf_counter()
    elapsed = end_time - start_time
    vecs_per_sec = NUM_VECTORS / elapsed
    
    print("-" * 50)
    print(f"Vectors compared: {NUM_VECTORS:,}")
    print(f"Time taken:       {elapsed * 1000:.2f} ms")
    print(f"Throughput:       {vecs_per_sec:,.0f} comparisons/sec")
    print("-" * 50)

if __name__ == "__main__":
    run_benchmark()
