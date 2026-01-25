"""
Simple script to run the PMS Portal server.
"""
import uvicorn

if __name__ == "__main__":
    print("Starting PMS Portal...")
    print("Access at: http://127.0.0.1:8000")
    print("Press Ctrl+C to stop")
    print("-" * 40)

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
