import requests
import time
import sys

API_URL = "http://localhost:6006"

def start_training():
    print(f"Connecting to Backend at {API_URL}...")
    
    # 1. Start Training Job
    try:
        payload = {
            "batch_size": 32,
            "lr": 3e-4,
            "max_steps": 5000,
            "ckpt_every": 200,
            "mode": "bc",
            "gamma": 0.99
        }
        resp = requests.post(f"{API_URL}/train/start", json=payload)
        resp.raise_for_status()
        job_id = resp.json().get("id")
        print(f"✅ Training Started! Job ID: {job_id}")
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to backend.")
        print("Run this first in a separate terminal:")
        print("  uvicorn rodoku_api.main:app --port 6006 --reload")
        return
    except Exception as e:
        print(f"❌ Error starting training: {e}")
        return

    # 2. Monitor Loop
    print("Monitoring progress (Ctrl+C to stop monitoring, training continues)...")
    try:
        last_step = -1
        while True:
            try:
                metrics = requests.get(f"{API_URL}/metrics").json()
                train_info = metrics.get("train")
                
                if not train_info or train_info["status"] != "running":
                    print("\nTraining job ended or stopped.")
                    break
                
                step = train_info["steps"]
                loss = train_info["last_loss"]
                
                if step != last_step:
                    print(f"Step {step:5d} | Loss: {loss:.6f}")
                    last_step = step
                    
                time.sleep(1)
            except KeyboardInterrupt:
                print("\nMonitoring stopped.")
                break
            except Exception as e:
                # Backend might be restarting or busy
                time.sleep(1)
                
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    start_training()
