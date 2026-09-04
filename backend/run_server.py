import os, uvicorn
from dotenv import load_dotenv
load_dotenv()
if __name__=="__main__":
    uvicorn.run("backend.app:app",
        host=os.getenv("HOST","0.0.0.0"),
        port=int(os.getenv("PORT","8787")),
        reload=False)
