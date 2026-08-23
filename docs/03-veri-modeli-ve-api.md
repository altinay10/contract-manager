# 03 — Veri Modeli ve API Sözleşmesi

## 1. PostgreSQL Şeması (özet DDL)

```sql
-- ---------- Kullanıcı & yetki ----------
users(id, email, full_name, department, role, is_active, created_at)
-- role: SATIN_ALMA | HUKUK | UYUM | BILGI_GUVENLIGI | YONETICI | ADMIN

-- ---------- Sözleşme dosyası ----------
contracts(
  id uuid pk, title text, counterparty_name text, counterparty_tax_no text,
  contract_type text,            -- YAZILIM|SAAS|DONANIM|HIZMET|DIS_KAYNAK|CERCEVE
  status text,                   -- YUKLENDI|ISLENIYOR|ANALIZ_HAZIR|INCELEMEDE|TAMAMLANDI|HATA
  value_amount numeric, value_currency text, term_months int,
  auto_renew bool, involves_personal_data bool, is_outsourcing bool,
  risk_score numeric, risk_band text,  -- YESIL|SARI|KIRMIZI
  owner_id fk users, created_at, updated_at
)

documents(
  id uuid pk, contract_id fk, version int, filename text, mime text,
  storage_key text, sha256 text, page_count int, ocr_used bool,
  uploaded_by fk users, uploaded_at
)

-- normalize edilmiş tam metin + offset haritası
document_texts(document_id fk pk, raw_text text, normalized_text text,
               page_offsets jsonb)   -- [{page:1, start:0, end:2814}, ...]

-- ---------- Yapı ----------
clauses(
  id uuid pk, document_id fk, parent_id fk clauses null,
  number text,             -- "7", "7.2", "7.2.a"
  heading text, text text,
  level int, order_index int,
  char_start int, char_end int, page_from int, page_to int,
  embedding vector(1024)
)

clause_types(                       -- playbook kayıtları (YAML'dan seed)
  code text pk, name_tr text, name_en text, category text,
  obligation text,                  -- ZORUNLU|ONERILEN|OPSIYONEL|YASAK
  applies_to text[], weight int,
  ideal_text_tr text, acceptable_variants jsonb, red_lines jsonb,
  detection_hints jsonb, legal_basis jsonb, negotiation_argument_tr text,
  severity_if_missing text, severity_if_weak text,
  version int, is_active bool, updated_by fk users, updated_at
)

clause_classifications(clause_id fk, code fk clause_types,
                       confidence numeric, method text, primary key(clause_id, code))

-- ---------- Bulgular ----------
findings(
  id uuid pk, contract_id fk, document_id fk, clause_id fk null,   -- MISSING ise null
  code fk clause_types,
  finding_type text,        -- RED_LINE|WEAK|MISSING|ONE_SIDED|AMBIGUOUS|INTERNAL_CONFLICT|CROSS_REF_ERROR|INFO
  severity text,            -- KRITIK|YUKSEK|ORTA|DUSUK|BILGI
  title text, rationale text,
  quote text, quote_char_start int, quote_char_end int,
  legal_basis jsonb,        -- yalnız playbook'tan seçili
  score numeric,
  detected_by text,         -- LLM|RULE|HYBRID
  prompt_version text, model_id text,
  verified bool, verification_notes text,
  status text,              -- ACIK|KABUL|REDDEDILDI|MUZAKEREDE|COZULDU
  created_at
)

recommendations(
  id uuid pk, finding_id fk, proposed_text text, change_summary text,
  negotiation_note text, fallback_text text,   -- kabul edilebilir 2. seçenek
  accepted bool null, edited_text text, edited_by fk users, updated_at
)

finding_comments(id, finding_id fk, user_id fk, body text, created_at)

-- ---------- Karşılaştırma ----------
document_diffs(id, contract_id, from_document_id, to_document_id,
               diff jsonb, generated_at)

-- ---------- Mevzuat / referans ----------
regulations(id, code, title, authority, article, text, effective_date,
            source_url, embedding vector(1024), version)

-- ---------- İzlenebilirlik ----------
analysis_runs(id, contract_id, document_id, stage, status, started_at,
              finished_at, error text, config_snapshot jsonb)
llm_calls(id, run_id, agent, prompt_id, prompt_version, model_id,
          input_tokens, output_tokens, cost_usd, latency_ms, ok bool)
dropped_findings(id, run_id, payload jsonb, reason text)
audit_log(id, user_id, action, entity_type, entity_id, ip, meta jsonb, at)
```

**İndeksler:** `clauses.embedding` → `ivfflat`; `findings(contract_id, severity)`;
`audit_log(at)` partition (aylık).

## 2. Durum Makineleri
**Sözleşme:** `YUKLENDI → ISLENIYOR → ANALIZ_HAZIR → INCELEMEDE → TAMAMLANDI`
(her yerden `HATA`'ya düşebilir; yeni sürüm yüklenince `YUKLENDI`'ye döner)

**Bulgu:** `ACIK → (KABUL | REDDEDILDI) → MUZAKEREDE → COZULDU`
`REDDEDILDI` seçilirken **zorunlu gerekçe** alınır → bu veri playbook iyileştirmesinin
ham maddesidir (yanlış pozitif analizi).

## 3. REST API (v1)

```
POST   /api/v1/contracts                     # meta ile birlikte kayıt aç
POST   /api/v1/contracts/{id}/documents      # dosya yükle (multipart) → analiz tetikler
GET    /api/v1/contracts?status=&band=&q=    # liste + filtre
GET    /api/v1/contracts/{id}                # özet + skor + sayaçlar
GET    /api/v1/contracts/{id}/events         # SSE: aşama ilerlemesi
GET    /api/v1/documents/{id}/text           # normalize metin + offsetler
GET    /api/v1/documents/{id}/clauses        # ağaç yapısı
GET    /api/v1/contracts/{id}/findings       # ?severity=&type=&code=
PATCH  /api/v1/findings/{id}                 # status, not
POST   /api/v1/findings/{id}/comments
GET    /api/v1/findings/{id}/recommendation
PATCH  /api/v1/recommendations/{id}          # metni düzenle / kabul et
POST   /api/v1/contracts/{id}/reports        # {format: DOCX_REDLINE|PDF_SUMMARY|XLSX_FINDINGS}
GET    /api/v1/contracts/{id}/diff?from=&to=
POST   /api/v1/contracts/{id}/reanalyze      # {stages:[8,9,10]} — kısmi yeniden çalıştırma

GET    /api/v1/playbook                      # madde tipleri
POST   /api/v1/playbook                      # yeni kayıt (ADMIN/HUKUK)
PUT    /api/v1/playbook/{code}               # sürümlü güncelleme
GET    /api/v1/playbook/{code}/impact        # bu kural kaç sözleşmede tetiklendi

GET    /api/v1/dashboard/stats               # portföy görünümü
GET    /api/v1/admin/llm-usage               # maliyet/token raporu
```

## 4. Çekirdek Veri Sözleşmesi — `Finding` (JSON)
Bu şema hem LLM çıktısı hem API cevabı olarak kullanılır (tek doğruluk kaynağı):

```json
{
  "code": "LIMITATION_OF_LIABILITY",
  "clause_number": "12.3",
  "finding_type": "RED_LINE",
  "severity": "KRITIK",
  "title": "Sorumluluk tavanı son 3 aylık bedelle sınırlandırılmış",
  "rationale": "Madde, tedarikçinin toplam sorumluluğunu son 3 ayda ödenen bedelle sınırlıyor ve gizlilik/kişisel veri ihlallerini istisna tutmuyor. Olası bir veri ihlalinde bankanın maruz kalacağı idari para cezası ve müşteri tazminatı bu tavanın çok üzerindedir.",
  "quote": "Tedarikçi'nin işbu Sözleşme'den doğan toplam sorumluluğu, talebin doğduğu tarihten önceki üç (3) ayda ödenen bedeli aşamaz.",
  "quote_char_start": 41822,
  "quote_char_end": 41961,
  "legal_basis": ["TBK m.115", "SAT-POL-014"],
  "confidence": 0.93
}
```
Ek kısıtlar: `legal_basis` **enum** (playbook'taki dayanaklar), `quote` metinde birebir
bulunmak zorunda, `rationale` ≤ 600 karakter, `severity` playbook aralığında.
