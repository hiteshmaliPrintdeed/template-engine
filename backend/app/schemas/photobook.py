from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class PhotoMeta(BaseModel):
    id: str
    filename: str
    url: str  # Alias for preview_url (used by frontend for smooth 60fps rendering)
    preview_url: Optional[str] = None  # ~1200px WebP for canvas/editor UI
    original_url: Optional[str] = None # Original high-res file for 300 DPI print export
    thumbnail_url: Optional[str] = None # ~256px WebP for photo tray / grid
    original_synced: bool = False      # Track background HD print asset sync status
    width: int = 1200
    height: int = 900
    aspect_ratio: float = 1.33
    dominant_colors: List[str] = Field(default_factory=list)
    score: Optional[float] = 0.8
    blur_score: Optional[float] = None
    face_count: Optional[int] = 0
    shell_phash: Optional[str] = ""
    core_phash: Optional[str] = ""
    is_hero_candidate: Optional[bool] = False

    # ------------------------------------------------------------------
    # Stage 1.2 — the filter engine's output, carried through to the solver.
    #
    # These fields existed only inside filter_engine's per-photo dicts and were
    # dropped when PhotoMeta was constructed at ingest, which left four
    # downstream systems running on nulls:
    #   shell_phash/core_phash -> cluster_photos_2tier_engine (spread grouping)
    #   timestamp_epoch/lat/lon -> partition_macro_chapters (story chapters)
    #   hero_score              -> cover selection
    #   dominant_colors         -> colour theming
    # ------------------------------------------------------------------

    # Temporal / geographic — drives partition_macro_chapters()
    timestamp_epoch: Optional[float] = 0.0   # epoch seconds; 0 == unknown
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Layout intelligence — drives hero selection and slot sizing
    hero_score: Optional[float] = 0.0        # 0-100, from compute_hero_score()
    # DOUBLE_PAGE_HERO (>=75 & landscape) | FULL_PAGE_HERO (>=62) | STANDARD_FRAME
    layout_role: Optional[str] = "STANDARD_FRAME"
    # Advisory only: the filter engine runs per ingest chunk, so this flag is
    # chunk-local. Session-wide cover selection must rank on hero_score, which
    # is computed per photo independently and is therefore globally comparable.
    is_event_cover_hero: Optional[bool] = False

    # Additional quality signals
    tenengrad_score: Optional[float] = None
    contrast_score: Optional[float] = None

    # ------------------------------------------------------------------
    # S3 direct upload — storage keys, for server-side use.
    #
    # These are NOT what the browser renders: url/preview_url/thumbnail_url stay
    # the durable "/uploads/{key}" strings, because those same values get
    # persisted into jobs.variations_json and read back by the reshuffle path,
    # where an expiring signed URL would rot. Keys exist so confirm can verify
    # an upload, retention can delete by prefix, and the PDF resolver can find
    # an original without probing seven extensions.
    #
    # Legacy rows have these as None; every consumer falls back to recomputing
    # storage_key(...), so they are an optimisation rather than a dependency.
    # They carry no bucket name or credential, so exposing them is harmless.
    # ------------------------------------------------------------------
    thumbnail_key: Optional[str] = None
    original_key: Optional[str] = None
    # Client-declared original size, from the ingest metadata. An admission hint
    # for presign-time quota reservation only — never accounting, which comes
    # from head_object at confirm time.
    declared_bytes: Optional[int] = 0

class TemplateSlot(BaseModel):
    id: str
    type: str  # "photo" or "text"
    x_pct: float
    y_pct: float
    w_pct: float
    h_pct: float
    target_aspect: Optional[float] = 1.0
    role: Optional[str] = "photo"
    photo_id: Optional[str] = None
    photo_url: Optional[str] = None
    text_content: Optional[str] = None
    effective_dpi: Optional[float] = None
    dpi_quality: Optional[str] = "excellent"  # "excellent" (>=250), "warning" (150-249), "alert" (<150)

class TemplateModel(BaseModel):
    id: str
    name: str
    photo_count: int
    text_condition: str  # "no_text", "short_text", "long_text"
    slots: List[TemplateSlot]

class SinglePage(BaseModel):
    page_number: int
    background_color: str
    text_color: str
    slots: List[TemplateSlot]
    title_caption: Optional[str] = None

class SpreadPair(BaseModel):
    spread_index: int
    left_page: SinglePage
    right_page: SinglePage

class CoverPhoto(BaseModel):
    """One photo occupying a slot on a cover."""
    photo_id: str
    url: str                        # thumbnail URL — never the full-res original
    aspect_ratio: float = 1.33
    hero_score: float = 0.0


class PhotobookVariation(BaseModel):
    id: str
    variation_title: str
    theme_name: str
    cover_title: str
    cover_subtitle: str

    # Stage 1.5: covers were a single `cover_image_url: str`, so the API could
    # not express a multi-photo cover at all. The frontend's "4-photo collage"
    # rendered that one URL four times, and all three variations received the
    # same photo (`photos[0]`, upload order) — which is why the covers read as
    # dummy placeholders.
    #
    # cover_style is chosen by the backend because only the producer knows how
    # many photos it supplied; the frontend previously guessed via `idx % 3`.
    cover_style: str = "SPLIT_BANNER"          # SPLIT_BANNER | HERO_BAND | COLLAGE_2X2
    cover_photos: List[CoverPhoto] = Field(default_factory=list)
    # DEPRECATED: mirrors cover_photos[0].url so nothing breaks mid-migration.
    cover_image_url: str = ""

    base_color: str
    accent_color: str
    text_color: str
    spreads: List[SpreadPair]

class GenerateVariationsRequest(BaseModel):
    photo_ids: List[str]
    user_prompt: str = ""
    # Stage 1.4: lets the job worker load photos with one indexed query instead
    # of chunking the id list into `IN (...)` clauses of 500.
    session_id: Optional[str] = None
    # Stage 3.2: Guided Story Studio content & cover typography preferences
    custom_title: Optional[str] = None
    include_text: bool = True
    subtitle: Optional[str] = None
    # Opt-in: let Gemini see ~3 representative thumbnails per story segment to
    # write captions. False (and absent, for older clients) sends no photos.
    use_photo_vision: bool = False


class SuggestTitlesRequest(BaseModel):
    user_prompt: str = ""
    session_id: Optional[str] = None
    photo_count: Optional[int] = 0


class SuggestTitlesResponse(BaseModel):
    titles: List[str]
    subtitles: List[str]
    category: str
    suggested_captions: List[str]


class SingleSpreadReshuffleRequest(BaseModel):
    spread: SpreadPair
    theme_name: str = "Warm"
    seed: int = 1
    session_id: Optional[str] = None


class VariationsReshuffleRequest(BaseModel):
    job_id: str
    seed_offset: int = 1
    # Stage 1.6: required so reshuffle reloads THIS session's photos.
    # Stage 3.2: also used to look up persisted include_text/custom_title/subtitle.
    session_id: Optional[str] = None


# Aliases matching the PRD schema names
ReshuffleSpreadRequest = SingleSpreadReshuffleRequest
ReshuffleVariationsRequest = VariationsReshuffleRequest


class GenerateVariationsResponse(BaseModel):
    theme_name: str
    variations: List[PhotobookVariation]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # "processing", "completed", "failed"
    progress: int  # 0 to 100
    message: str
    result: Optional[GenerateVariationsResponse] = None

