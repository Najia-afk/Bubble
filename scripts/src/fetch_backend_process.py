# fetch_backend_process.py
import logging
import multiprocessing as mp
from multiprocessing import Pool
from utils.logging_config import setup_logging
from scripts.src.fetch_erc20_price_history_coingecko import fetch_erc20_price_history
from scripts.src.fetch_scan_token_erc20_transfert import rotate_and_fetch
import signal

backend_logger = setup_logging('fetch_backend_process.log')

def init_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def run_tasks(tasks, num_processes=None):
    if num_processes is None:
        num_processes = mp.cpu_count()
    with Pool(processes=num_processes, initializer=init_worker) as pool:
        result = pool.starmap_async(execute_task, tasks)
        try:
            result.get(86400)  # Wait at most 24 hours for completion
        except KeyboardInterrupt:
            backend_logger.info("Terminating due to KeyboardInterrupt")
            pool.terminate()
        except Exception as e:
            backend_logger.error(f"Unexpected error: {e}")
            pool.terminate()
        else:
            pool.close()
        pool.join()

def execute_task(func, args):
    try:
        backend_logger.info(f"Starting task {func.__name__} with arguments {args}")
        func(*args)
        backend_logger.info(f"Task {func.__name__} completed successfully")
    except Exception as e:
        backend_logger.error(f"Error executing task {func.__name__}: {e}")

if __name__ == "__main__":
    tasks = [
        (fetch_erc20_price_history, ()),
        (rotate_and_fetch, ('POL',)),
    ]

    mp.set_start_method('fork')  # Adjust based on your environment
    run_tasks(tasks)

#nohup python3 -m scripts.src.fetch_backend_process &
#ps aux | grep 'fetch_backend_process' | grep -v grep | awk '{print $2}' | xargs kill
#ps aux | grep 'fetch_backend_process' | grep -v grep | awk '{print $2}' | xargs kill -9
#pkill -f fetch_backend_process
#pkill -9 -f fetch_backend_process
#glances

