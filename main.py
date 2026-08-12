import os
import uuid
import shutil
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from database import (
    init_db, 
    get_total_leads, 
    get_leads_paginated, 
    clear_all_leads
)
from lead_processor import (
    process_new_leads_sheet, 
    import_historical_sheet
)

app = FastAPI(title="Lead Filter API")

# Habilitar CORS para desenvolvimento local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar o banco de dados no startup
@app.on_event("startup")
def startup_event():
    init_db()
    # Criar pasta para arquivos temporários se não existir
    os.makedirs("temp_exports", exist_ok=True)

# Dicionário em memória para armazenar os arquivos processados e permitir download
# { "file_uuid": { "bytes": b"...", "filename": "..." } }
PROCESSED_FILES = {}

@app.get("/api/stats")
def get_stats():
    try:
        total = get_total_leads()
        return {"total_leads": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/import-historical")
async def import_historical(
    file: UploadFile = File(...),
    col_name: Optional[str] = Form(None),
    col_email: Optional[str] = Form(None),
    col_phone: Optional[str] = Form(None)
):
    try:
        contents = await file.read()
        
        custom_mapping = None
        if col_name:
            custom_mapping = {
                "name": col_name,
                "email": col_email,
                "phone": col_phone
            }
            
        inserted_count, stats = import_historical_sheet(
            contents, 
            file.filename, 
            custom_mapping=custom_mapping
        )
        
        return {
            "success": True,
            "message": f"Histórico importado com sucesso. {inserted_count} novos leads adicionados.",
            "inserted_count": inserted_count,
            "total_rows": stats.get("total_rows", 0),
            "mapping": stats.get("col_mapping", {})
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/process-leads")
async def process_leads(
    file: UploadFile = File(...),
    col_name: Optional[str] = Form(None),
    col_email: Optional[str] = Form(None),
    col_phone: Optional[str] = Form(None)
):
    try:
        contents = await file.read()
        
        custom_mapping = None
        if col_name:
            custom_mapping = {
                "name": col_name,
                "email": col_email,
                "phone": col_phone
            }
            
        filtered_bytes, stats = process_new_leads_sheet(
            contents, 
            file.filename, 
            custom_mapping=custom_mapping
        )
        
        if filtered_bytes is None:
            raise HTTPException(status_code=400, detail="Planilha vazia ou sem dados válidos.")
            
        # Salvar em cache em memória para download
        file_id = str(uuid.uuid4())
        
        # Gerar o nome de saída (ex: original_filtrado.xlsx)
        base_name, ext = os.path.splitext(file.filename)
        output_filename = f"{base_name}_filtrado{ext}"
        
        # Salvar também em disco físico na pasta temp_exports para segurança
        temp_path = os.path.join("temp_exports", f"{file_id}{ext}")
        with open(temp_path, "wb") as f:
            f.write(filtered_bytes)
            
        PROCESSED_FILES[file_id] = {
            "path": temp_path,
            "filename": output_filename
        }
        
        return {
            "success": True,
            "file_id": file_id,
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/download-file/{file_id}")
def download_file(file_id: str):
    file_info = PROCESSED_FILES.get(file_id)
    
    if not file_info or not os.path.exists(file_info["path"]):
        raise HTTPException(status_code=404, detail="Arquivo expirado ou não encontrado.")
        
    return FileResponse(
        path=file_info["path"],
        filename=file_info["filename"],
        media_type="application/octet-stream"
    )

@app.get("/api/leads")
def get_leads(page: int = 1, page_size: int = 50, search: str = ""):
    try:
        leads, total = get_leads_paginated(page, page_size, search)
        return {
            "leads": leads,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/leads")
def clear_db():
    try:
        clear_all_leads()
        return {"success": True, "message": "Banco de dados limpo com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Servir a página principal e arquivos estáticos
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

# Servir arquivos estáticos (CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    # Teste de deploy para validar persistência de dados no Railway
    port = int(os.environ.get("PORT", 8000))
    # No Railway ou produção, usamos host 0.0.0.0 e reload=False se DATA_DIR estiver definido
    is_prod = os.environ.get("DATA_DIR") is not None
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=not is_prod)
