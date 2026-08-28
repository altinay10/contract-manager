"""Veri modeli.

Kilit tasarım: analiz hattı **checkpoint'lidir**. Her aşamanın ve risk analizinde her
maddenin durumu ayrı satırda tutulur; süreç yarıda kesilirse kaldığı yerden devam eder.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Aşama tanımları — sıra buradan okunur, kod başka yerde sıralamayı bilmez.
# --------------------------------------------------------------------------- #
STAGES: list[tuple[str, str, str]] = [
    ("INGEST",        "Alım",                "Dosya doğrulama, SHA-256 özeti, tür tespiti"),
    ("EXTRACT",       "Metin Çıkarma",       "PDF/DOCX metin katmanı ve sayfa sınırları"),
    ("NORMALIZE",     "Normalizasyon",       "Satır birleştirme, üstbilgi temizliği, karakter haritası"),
    ("SEGMENT",       "Madde Ayrıştırma",    "Madde / fıkra / bent hiyerarşisi, tanımlar ve ekler"),
    ("META",          "Meta Çıkarımı",       "Taraflar, bedel, süre, yenileme, damga vergisi"),
    ("CLASSIFY",      "Madde Sınıflandırma", "Her madde hangi playbook tipine karşılık geliyor"),
    ("DETERMINISTIC", "Ön Kontroller",       "Belirsiz ifade, çapraz atıf, eksik madde adayları"),
    ("RISK",          "Risk Analizi",        "Kırmızı çizgi kontrolü ve kritik maddelerde çoklu mercek"),
    ("VERIFY",        "Doğrulama",           "Alıntı metinde birebir var mı; kritik bulgularda karşı-görüş"),
    ("REPORT",        "Rapor",               "Skorlama, alternatif madde metni, sonuç belgesi"),
]
STAGE_KEYS = [s[0] for s in STAGES]
STAGE_LABEL = {k: (lbl, desc) for k, lbl, desc in STAGES}


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(500), default="")
    filename: Mapped[str] = mapped_column(String(500), default="")
    storage_path: Mapped[str] = mapped_column(String(1000), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(120), default="")

    # bağlam (skorlama çarpanlarını besler)
    contract_type: Mapped[str] = mapped_column(String(40), default="SAAS")
    involves_personal_data: Mapped[bool] = mapped_column(Boolean, default=True)
    is_outsourcing: Mapped[bool] = mapped_column(Boolean, default=False)

    # analiz çıktısı
    status: Mapped[str] = mapped_column(String(30), default="YUKLENDI", index=True)
    counterparty: Mapped[str] = mapped_column(String(300), default="")
    value_text: Mapped[str] = mapped_column(String(120), default="")
    term_text: Mapped[str] = mapped_column(String(120), default="")
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_band: Mapped[str] = mapped_column(String(20), default="")
    veto_reason: Mapped[str] = mapped_column(Text, default="")

    raw_text: Mapped[str] = mapped_column(Text, default="")
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    page_map: Mapped[list | None] = mapped_column(JSON, default=list)
    meta_json: Mapped[dict | None] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    clauses: Mapped[list["Clause"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    findings: Mapped[list["Finding"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    runs: Mapped[list["AnalysisRun"]] = relationship(back_populates="contract", cascade="all, delete-orphan")


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)

    number: Mapped[str] = mapped_column(String(40), default="")
    heading: Mapped[str] = mapped_column(String(400), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    page_from: Mapped[int] = mapped_column(Integer, default=0)

    codes: Mapped[list | None] = mapped_column(JSON, default=list)  # [{code, confidence, method}]

    contract: Mapped[Contract] = relationship(back_populates="clauses")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    clause_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    code: Mapped[str] = mapped_column(String(80), default="", index=True)
    clause_number: Mapped[str] = mapped_column(String(40), default="")
    finding_type: Mapped[str] = mapped_column(String(30), default="WEAK")
    severity: Mapped[str] = mapped_column(String(20), default="ORTA", index=True)

    title: Mapped[str] = mapped_column(String(500), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    quote: Mapped[str] = mapped_column(Text, default="")
    # Alinti KANIT mi (maddedeki sorunlu ifade) yoksa BAGLAM mi (korumanin
    # bulunmadigi maddenin metni)? Yokluk bulgularinda alinti iddiayi kanitlamaz;
    # rapor bunu kanit gibi gostermemeli.
    quote_is_evidence: Mapped[bool] = mapped_column(Boolean, default=True)
    legal_basis: Mapped[list | None] = mapped_column(JSON, default=list)

    proposed_text: Mapped[str] = mapped_column(Text, default="")
    negotiation_note: Mapped[str] = mapped_column(Text, default="")

    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    detected_by: Mapped[str] = mapped_column(String(20), default="LLM")
    lens: Mapped[str] = mapped_column(String(30), default="")

    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_note: Mapped[str] = mapped_column(Text, default="")
    rebuttal: Mapped[str] = mapped_column(Text, default="")  # K7 karşı-görüş gerekçesi

    status: Mapped[str] = mapped_column(String(20), default="ACIK")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    contract: Mapped[Contract] = relationship(back_populates="findings")


class DroppedFinding(Base):
    """Doğrulamadan geçemeyen bulgular. Sessizce yutulmaz — eval için altın veri."""
    __tablename__ = "dropped_findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    payload: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# FAILSAFE / CHECKPOINT ÇEKİRDEĞİ
# --------------------------------------------------------------------------- #
class AnalysisRun(Base):
    """Bir analiz denemesi. Süreç çökerse bu satır 'RUNNING' kalır ve
    açılışta orphan taraması onu kaldığı yerden devam ettirir."""
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)

    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING/RUNNING/DONE/FAILED
    current_stage: Mapped[str] = mapped_column(String(30), default="")
    # Bu run'i yuruten surecin acilis kimligi. Uygulama yeniden basladiginda
    # kimlik degisir; farkli kimlikli RUNNING run oksuzdur - kalp atisi taze olsa bile.
    owner_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    # Isbirlikli iptal: is parcacigi zorla oldurulmez, asama sinirlarinda kontrol edilir.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    resumed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")

    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    contract: Mapped[Contract] = relationship(back_populates="runs")
    checkpoints: Mapped[list["StageCheckpoint"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="StageCheckpoint.position"
    )


class StageCheckpoint(Base):
    """Aşama başına kalıcı durum. DONE olan aşama yeniden çalıştırılmaz."""
    __tablename__ = "stage_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "stage", name="uq_run_stage"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)

    stage: Mapped[str] = mapped_column(String(30), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/RUNNING/DONE/FAILED/SKIPPED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(String(300), default="")   # canlı alt-durum: "madde 34 / 62"
    items_total: Mapped[int] = mapped_column(Integer, default=0)
    items_done: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    run: Mapped[AnalysisRun] = relationship(back_populates="checkpoints")


class WorkItem(Base):
    """Aşama içi ince taneli checkpoint (madde başına LLM çağrısı).

    Risk analizi 62 maddenin 40'ında çökerse, devam ettiğinde yalnız kalan 22 madde
    işlenir. Pahalı olan kısım budur; tekrar etmemesi gerekir.
    """
    __tablename__ = "work_items"
    __table_args__ = (UniqueConstraint("contract_id", "stage", "item_key", name="uq_item"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(30), index=True)
    item_key: Mapped[str] = mapped_column(String(120), index=True)

    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/DONE/FAILED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LLMCall(Base):
    """Maliyet ve önbellek takibi."""
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    agent: Mapped[str] = mapped_column(String(60), default="")
    prompt_id: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(60), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Denetim izi — kim, ne zaman, neyi yaptı.

    Bankacilik denetiminde goruntuleme dahil islemlerin kaydi zorunludur.
    Append-only kullanilir; uygulama bu tabloyu guncellemez veya silmez.
    """
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user: Mapped[str] = mapped_column(String(120), default="", index=True)
    action: Mapped[str] = mapped_column(String(60), default="", index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(400), default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(String(32), index=True)
    fmt: Mapped[str] = mapped_column(String(20), default="DOCX")
    path: Mapped[str] = mapped_column(String(1000), default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
