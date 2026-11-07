export interface AudioRef { job_id: number; meter_id: string; voice_id: string; steps: number; duration: number }
export interface VerseSource { work: string; reference: string; url?: string | null; edition?: string | null }
export interface Verse {
  id: string
  title: string | null
  text: string[]
  source: VerseSource
  notes: string | null
  meter_hint: string | null
  audio: AudioRef[]
  meanings?: Meanings
}
export interface NewVerse {
  id: string; title?: string | null; text: string[] | string; source: VerseSource
  notes?: string | null; meter_hint?: string | null
}
export interface Meter { id: string; name: string; syllable_count: number | null; sec_per_syll: number; is_prose: number | boolean }
export interface Voice { id: string; name: string; notice: string | null }
export type JobStatus = 'queued' | 'awaiting_result' | 'running' | 'aligning' | 'done' | 'failed' | 'cancelled'
export interface Job {
  id: number; verse_id: string; meter_id: string; voice_id: string
  executor: string; device: string; steps: number
  status: JobStatus; progress: number; log?: string | null; error: string | null
  created_at?: string
  asset?: { duration: number; aligned: number | boolean } | null
}
export interface Settings {
  executor: string; device: string; steps: string | number
  colab_drive_dir?: string; colab_timeout_s?: string | number
}
export interface SettingsUpdate {
  executor?: string; device?: string; steps?: number
  colab_drive_dir?: string; colab_timeout_s?: number
}
export interface ExecutorInfo { name: string; label: string; description: string }
export interface MeterSuggestion {
  meter_id: string; meter: string; syllables_per_segment: number | number[]; reason: string; exact: boolean
}
export interface AlignSyllable { slp1: string; start: number; end: number }
export interface AlignWord { text: string; slp1: string; start: number; end: number; syllables: AlignSyllable[] }
export interface Alignment { audio_duration: number; lines: { words: AlignWord[] }[] }
export interface CreateJob {
  verse_id: string; meter_id: string; voice_id?: string
  executor?: string; device?: string; steps?: number; seed?: number
}
export interface ExecutorHealth { [k: string]: unknown; ok?: boolean }
export type MeaningOrigin = 'seed' | 'user' | 'machine'
export interface WordMeaning {
  line: number; index: number; text: string; meaning: string; grammar: string | null
  origin: MeaningOrigin; reviewed: boolean
}
export interface MeaningSummary { translation: string; explanation: string | null; origin: MeaningOrigin; reviewed: boolean }
export interface Meanings { words: WordMeaning[]; summary: MeaningSummary | null }
export interface MeaningsUpdate {
  words: { line: number; index: number; text: string; meaning: string; grammar?: string | null }[]
  summary?: { translation: string; explanation?: string | null }
  origin?: MeaningOrigin; reviewed?: boolean
}

// ---- Epics (Ramayana browser). Shapes follow sources/ramayan/README.md; all fields tolerant. ----
export interface EpicSummary {
  id: string; name: string; name_sa?: string | null; kanda_count: number; verse_count: number
  book_label?: string | null; book_label_sa?: string | null; chapter_label?: string | null; chapter_label_sa?: string | null
}
export type EpicLayer = 'critical' | 'southern_only' | 'supplements_unplaced' | string
export interface KandaSummary { number: number; name_sa: string | null; name_en: string | null; sarga_count: number; verse_count: number }
export interface SargaSummary {
  sarga: number; title_hi: string | null; title_en: string | null; title_sa?: string | null; verse_count: number
  layer?: EpicLayer | null; adhyaya_display?: number | null
}
export interface SargaMeta {
  title_hi_from_in?: string | null; title_en_from_in?: string | null; intro_en_from_net?: string | null
  // Mahabharata _adhyaya.json
  meanings?: EpicMeanings | null
  southern_chapters?: { head?: string | null; topic?: string | null }[] | null
  translations_unplaced_verse?: unknown[] | null
  supplements_unplaced_verse?: unknown[] | null
  review_status?: string | null; licence_note?: string | null
  [k: string]: unknown
}
export interface EpicTextVariant { source?: string | null; lines?: string[] | null; locators?: string[] | null; refs?: string[] | null }
export interface CriticalText extends EpicTextVariant { punctuated_derived?: string | null; smith_ids?: string[] | null; kinds?: string[] | null }
export interface GitapressText extends EpicTextVariant { ocr_flags?: unknown[] | null }
export interface EpicVerseText {
  critical_smith?: CriticalText | null
  vulgate_net?: EpicTextVariant | null
  vulgate_in?: EpicTextVariant | null
  vulgate_gitapress?: GitapressText | null
  southern_sarit?: EpicTextVariant | null
  // Harivamsha (GRETIL IAST + machine-transliterated Devanagari)
  raw_source?: string[] | string | null
  iast_original?: string[] | null
  padas_devanagari?: string[] | null
  devanagari_machine_transliterated?: string[] | null
}
export interface EpicPassage {
  passage_id?: string; kind?: string; apparatus?: string[] | null; placement?: string | null
  lines?: ({ id?: string; text?: string } | string)[] | null
}
export interface WordDiff { a?: string; b?: string }
export interface EpicAlignmentRow {
  smith?: string | null; net?: string | null; in?: string | null; gp?: string | null
  similarity?: Record<string, number> | null
  confidence?: string | null
  word_diffs?: Record<string, WordDiff[]> | null
}
export interface MeaningWord {
  roman_itrans?: string; devanagari_machine_converted?: string; english?: string
  sanskrit?: string; hindi?: string
}
export interface EpicMeaningItem {
  source?: string | null; spans_beyond_this_verse?: boolean | null
  text?: string | null; words?: MeaningWord[] | null
  translator?: string | null; provenance?: string | null; note?: string | null
  net_locator?: string | null; in_locator?: string | null; verse_ref?: string | null
  ocr_flags?: unknown[] | null
  rights?: string | null; licence_note?: string | null; ref?: string | null; unit_id?: string | null; granularity?: string | null
}
export type EpicMeaningKey =
  | 'english_translation' | 'english_word_by_word' | 'english_commentary'
  | 'hindi_translation' | 'hindi_word_by_word' | 'hindi_translation_gitapress'
export type EpicMeanings = Partial<Record<EpicMeaningKey, EpicMeaningItem[] | null>> & Record<string, EpicMeaningItem[] | null | undefined>
export interface EpicRefs {
  critical_smith?: { sarga?: number; verse?: number } | null
  vulgate_sarga?: number | null
  vulgate_net_locators?: string[] | null
  vulgate_in_locators?: string[] | null
  vulgate_gitapress_refs?: string[] | null
}
export interface EpicSupplement {
  passage_id?: string; kind?: string; apparatus?: string[] | null
  lines?: ({ id?: string; text?: string } | string)[] | null
  placement?: string | null
}
export interface CriticalNote { smith_ids?: string[]; comment?: string; star_passages?: { label?: string; lines?: string[] }[] }
export interface EpicVerse {
  id: string
  kind?: 'critical' | 'vulgate_only' | string
  seq_in_sarga?: number
  refs?: EpicRefs | null
  text?: EpicVerseText | null
  alignment?: EpicAlignmentRow[] | null
  meanings?: EpicMeanings | null
  critical_edition_notes?: (CriticalNote | string)[] | null
  flags?: string[] | null
  review_status?: string | null
  licence_note?: string | null
  supplements?: EpicSupplement[] | null
  passage?: EpicPassage | null
  machine_transliterated?: boolean | null; devanagari_origin?: string | null
  layer?: EpicLayer | null; adhyaya_display?: number | null
  kanda?: { number: number; name_sa?: string | null; name_en?: string | null; key?: string } | null
}
export interface SargaDetail {
  kanda: { number: number; name_sa: string | null; name_en: string | null }
  sarga: number
  layer?: EpicLayer | null
  meta?: SargaMeta | null
  verses: EpicVerse[]
  prev: { sarga: number; adhyaya_display?: number | null } | null
  next: { sarga: number; adhyaya_display?: number | null } | null
}

// ---- Epic batches (Colab batch flow) ----
export interface BatchScope {
  epic: string; kanda: number | null; sarga: number | null; verse_id: string | null
}
export interface BatchRequest extends BatchScope {
  voice_id: string; steps: number; seed?: number; meter_id: string | null
}
export interface BatchPreview {
  total: number; to_generate: number; skipped: number; unavailable: number
  meters: { meter_id: string; count: number }[]
  sample: { id: string; ref: string; meter_id: string }[]
}
export interface BatchCreated { batch_id: number | string; job_ids: number[]; count: number }
export type BatchId = number | string
export interface BatchSummary {
  id: BatchId; created_at: string; total: number; counts: Record<string, number>; [k: string]: unknown
}
export interface BatchJob { id: number; verse_id: string; status: JobStatus; progress: number; error: string | null }
export interface BatchDetail extends BatchSummary { jobs: BatchJob[] }
export interface BatchUploadResult { accepted: number; failed: number; ignored: number }
export interface BatchImportResult extends BatchUploadResult { missing: number }

export interface AlignUploadResult extends BatchUploadResult { batches: (number | string)[]; job_ids: number[] }
