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

    # Sunucunun kendi LLM anahtarı yalnızca giriş yapmış kullanıcılara ayrılır.
    # Parolasız yüklenen sözleşmeler kural katmanıyla analiz edilir (bkz. runner.execute).
    model_izinli: Mapped[bool] = mapped_column(Boolean, default=False)

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

    # Silme YUMUSAKTIR: damga konur, satir durur. Listeler ve bulgu/rapor
    # uclari silinmis sozlesmeyi gostermez ama hicbir veri kaybolmaz ve islem
    # /api/contracts/{id}/restore ile geri alinabilir. Kalici silme bilincli
    # olarak uygulanmadi: buradaki reports/llm_calls/work_items tablolarinin
    # contract_id'si yabanci anahtar DEGIL, yani satirin dusurulmesi onlari
    # sessizce oksuz birakir.
    silindi_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

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
    contract_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    # Karşılaştırma raporları için doldurulur; risk raporlarında boş kalır.
    # İndirme ucu rapor kimliğine bakar, bu alana değil — o yüzden
    # /api/reports/{id} iki tür için de değişmeden çalışır.
    comparison_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    fmt: Mapped[str] = mapped_column(String(20), default="DOCX")
    path: Mapped[str] = mapped_column(String(1000), default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- #
# SÜRÜM KARŞILAŞTIRMA
#
# Risk analizinden bağımsız ikinci bir akış: sözleşmenin eski ve yeni hâli
# karşılaştırılır. Contract/Clause/Finding tabloları bu akışta hiç kullanılmaz;
# ortak olan yalnızca metin çıkarma ve madde ayrıştırma fonksiyonlarıdır.
# --------------------------------------------------------------------------- #
# LLM kaldıraçları ayrı aşamalardır; böylece tek tek açılıp kapatılabilir ve
# katkıları ölçülebilir (docs/08 §7 ablasyon tablosu).
COMPARE_STAGES: list[tuple[str, str, str]] = [
    ("INGEST",     "Alım",                 "İki dosya doğrulanır, SHA-256 özeti alınır"),
    ("EXTRACT",    "Metin Çıkarma",        "Her iki sürümün metni ve sayfa sınırları"),
    ("SEGMENT",    "Birim Ayrıştırma",     "Maddeler ve kapsanmayan aralıklar birimlere bölünür"),
    ("ALIGN",      "Eşleştirme",           "Eski ve yeni birimler eşleştirilir"),
    ("ADJUDICATE", "Belirsiz Eşleştirme",  "Kararsız çiftler modele sorulur; model yoksa atlanır"),
    ("DIFF",       "Fark Çıkarma",         "Eşleşen birimlerde kelime bazında fark"),
    ("EXPLAIN",    "Açıklama",             "Her esaslı değişiklik yorumlanır"),
    ("VERIFY",     "Doğrulama",            "Açıklamanın çapaları gerçek farka karşı denetlenir"),
    ("REPORT",     "Rapor",                "Değişiklik raporu belgesi"),
]
COMPARE_STAGE_KEYS = [s[0] for s in COMPARE_STAGES]
COMPARE_STAGE_LABEL = {k: (lbl, desc) for k, lbl, desc in COMPARE_STAGES}

# Değişiklik türleri
CHANGE_TYPES = ("EKLENDI", "SILINDI", "DEGISTI", "TASINDI", "AYNI")

# Taraf etkisi — modelin doldurduğu alan. Model yoksa BELIRSIZ kalır.
IMPACTS = ("ALICI_LEHINE", "TEDARIKCI_LEHINE", "NOTR", "BELIRSIZ")

# Değişikliğin ağırlığı. Triyaj geçişinde model belirler; model yoksa
# deterministik yedek karar verir (farkta sayı/süre/tutar var mı).
MATERIALITY = ("ESASLI", "KUCUK", "BICIMSEL")


class Comparison(Base):
    """Bir karşılaştırma işi: iki dosya, durumu ve özeti."""
    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(500), default="")

    old_filename: Mapped[str] = mapped_column(String(500), default="")
    old_storage_path: Mapped[str] = mapped_column(String(1000), default="")
    old_sha256: Mapped[str] = mapped_column(String(64), default="")
    old_size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    new_filename: Mapped[str] = mapped_column(String(500), default="")
    new_storage_path: Mapped[str] = mapped_column(String(1000), default="")
    new_sha256: Mapped[str] = mapped_column(String(64), default="")
    new_size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # Sunucunun LLM anahtarı yalnızca giriş yapmış kullanıcılara ayrılır —
    # Contract.model_izinli ile birebir aynı kural (bkz. compare_runner.execute).
    model_izinli: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(30), default="YUKLENDI", index=True)
    stage: Mapped[str] = mapped_column(String(30), default="")
    stage_detail: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    # Bu işi yürüten sürecin açılış kimliği; yeniden başlatmada değişir.
    owner_id: Mapped[str] = mapped_column(String(32), default="", index=True)

    summary: Mapped[str] = mapped_column(Text, default="")
    stats_json: Mapped[dict | None] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    changes: Mapped[list["ClauseChange"]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan",
        order_by="ClauseChange.order_index",
    )


class ClauseChange(Base):
    """Tek bir değişiklik.

    `explanation` alanı boş olan satır 'henüz açıklanmadı' demektir; süreç
    yarıda kesilirse devam ederken yalnız bu satırlar işlenir. Ayrı bir
    checkpoint tablosuna gerek yok — verinin kendisi checkpoint.
    """
    __tablename__ = "clause_changes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    comparison_id: Mapped[str] = mapped_column(
        ForeignKey("comparisons.id", ondelete="CASCADE"), index=True
    )

    change_type: Mapped[str] = mapped_column(String(20), default="DEGISTI", index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)

    old_number: Mapped[str] = mapped_column(String(40), default="")
    old_heading: Mapped[str] = mapped_column(String(400), default="")
    old_text: Mapped[str] = mapped_column(Text, default="")
    new_number: Mapped[str] = mapped_column(String(40), default="")
    new_heading: Mapped[str] = mapped_column(String(400), default="")
    new_text: Mapped[str] = mapped_column(Text, default="")

    similarity: Mapped[float] = mapped_column(Float, default=0.0)
    # [{op: "equal"|"insert"|"delete", text: "..."}] — kelime bazlı fark
    word_diff: Mapped[list | None] = mapped_column(JSON, default=list)
    # Madde mi, kapsanmayan aralıktan türeyen birim mi?
    is_gap_unit: Mapped[bool] = mapped_column(Boolean, default=False)
    # Modele gönderilecek kadar önemli mi? (yalnız boşluk/noktalama ise değil)
    significant: Mapped[bool] = mapped_column(Boolean, default=True)

    explanation: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(String(20), default="BELIRSIZ")
    impact_note: Mapped[str] = mapped_column(Text, default="")
    explained_by: Mapped[str] = mapped_column(String(20), default="")
    # Triyaj geçişinin kararı; yalnız ESASLI olanlar ayrı çağrıyla yorumlanır.
    materiality: Mapped[str] = mapped_column(String(20), default="")
    # Modelin açıklamayı desteklemek için verdiği birebir alıntı.
    quote: Mapped[str] = mapped_column(Text, default="")

    # Çapa doğrulaması: açıklamadaki sayılar ve alıntı gerçek metinde var mı?
    # Başarısızlık açıklamayı SİLMEZ — kartta deterministik fark zaten duruyor.
    explanation_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_note: Mapped[str] = mapped_column(Text, default="")
    # K7 karşı-görüş gerekçesi; yalnız tedarikçi lehine sayılan değişikliklerde.
    rebuttal: Mapped[str] = mapped_column(Text, default="")
    # Bu eşleşmeyi hakem geçişi mi kurdu? (gri banttan kurtarılmış çift)
    adjudicated: Mapped[bool] = mapped_column(Boolean, default=False)

    comparison: Mapped[Comparison] = relationship(back_populates="changes")
