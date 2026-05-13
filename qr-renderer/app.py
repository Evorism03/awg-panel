from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
import io
import qrcode

app = FastAPI(title="AWG QR Renderer")


class RenderRequest(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/render")
def render(body: RenderRequest):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=14,
        border=8,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
