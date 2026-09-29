import React, { useState } from 'react';
import {
  Sparkles,
  Type,
  BookOpen,
  Image,
  Check,
  ArrowRight,
  RefreshCw,
  Compass,
  Edit3
} from 'lucide-react';

const OCCASION_PILLS = [
  'Road Trip',
  'Family Holiday',
  'Wedding Celebration',
  'Milestone',
  'Weekend Journey',
  'Birthday Gathering'
];

export default function AIChatbotWidget({
  userPrompt,
  setUserPrompt,
  onGenerate,
  isPhotoUploadComplete,
  uploadedCount,
  isLoading,
  sessionId
}) {
  const [promptInput, setPromptInput] = useState(userPrompt || '');
  const [selectedPill, setSelectedPill] = useState('');
  const [isSuggestingTitles, setIsSuggestingTitles] = useState(false);
  const [suggestions, setSuggestions] = useState(null);
  const [selectedTitleIdx, setSelectedTitleIdx] = useState(null);
  const [customTitle, setCustomTitle] = useState('');
  const [customSubtitle, setCustomSubtitle] = useState('');
  const [includeText, setIncludeText] = useState(true);
  // Opt-in, off by default: only when ticked are a few photos sent to Gemini.
  const [usePhotoVision, setUsePhotoVision] = useState(false);

  const handleSelectPill = (pill) => {
    setSelectedPill(pill);
    if (!promptInput.trim()) {
      setPromptInput(pill);
      setUserPrompt(pill);
    } else if (!promptInput.toLowerCase().includes(pill.toLowerCase())) {
      const next = `${pill} — ${promptInput}`;
      setPromptInput(next);
      setUserPrompt(next);
    }
  };

  const handlePromptChange = (e) => {
    const val = e.target.value;
    setPromptInput(val);
    setUserPrompt(val);
  };

  const handleSuggestTitles = async () => {
    const query = promptInput.trim() || selectedPill || 'Cherished Memories';
    setIsSuggestingTitles(true);
    try {
      const res = await fetch('/api/chat/suggest-titles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_prompt: query,
          photo_count: uploadedCount || 0,
          session_id: sessionId || null
        })
      });
      if (res.ok) {
        const data = await res.json();
        setSuggestions(data);
        if (data.titles && data.titles.length > 0) {
          setSelectedTitleIdx(0);
          setCustomTitle(data.titles[0]);
          setCustomSubtitle(
            (data.subtitles && data.subtitles[0]) || 'A COLLECTION OF MEMORIES'
          );
        }
      }
    } catch (err) {
      console.error('Title suggestion error:', err);
    } finally {
      setIsSuggestingTitles(false);
    }
  };

  const handlePickSuggestedCard = (idx) => {
    if (!suggestions || !suggestions.titles) return;
    setSelectedTitleIdx(idx);
    const title = suggestions.titles[idx] || '';
    const sub =
      (suggestions.subtitles &&
        suggestions.subtitles[idx % suggestions.subtitles.length]) ||
      'A COLLECTION OF MEMORIES';
    setCustomTitle(title);
    setCustomSubtitle(sub);
  };

  const handleCustomTitleInput = (e) => {
    setSelectedTitleIdx(null);
    setCustomTitle(e.target.value);
  };

  const handleCustomSubtitleInput = (e) => {
    setCustomSubtitle(e.target.value);
  };

  const handleLaunchGeneration = (e) => {
    if (e) e.preventDefault();
    const effectivePrompt =
      promptInput.trim() || selectedPill || 'Cherished Memories';
    setUserPrompt(effectivePrompt);

    const trimmedTitle = customTitle.trim() || null;
    const trimmedSubtitle = customSubtitle.trim() || null;

    onGenerate(effectivePrompt, {
      custom_title: trimmedTitle,
      include_text: includeText,
      subtitle: trimmedSubtitle,
      // Meaningless without captions, so never sent as true for photo-only books.
      use_photo_vision: includeText && usePhotoVision
    });
  };

  const displayTitlePreview =
    customTitle.trim() ||
    (promptInput.trim() ? promptInput.trim().toUpperCase() : 'YOUR PHOTOBOOK');

  const displaySubtitlePreview =
    customSubtitle.trim() || 'A COLLECTION OF MEMORIES';

  return (
    <div className="step-card studio-configurator-card">
      {/* Top Ingestion & Readiness Banner */}
      <div
        className="studio-status-banner"
        style={{
          backgroundColor: isPhotoUploadComplete
            ? 'var(--px-status-success-bg)'
            : 'var(--px-brand-iris-subtle)',
          borderColor: isPhotoUploadComplete
            ? 'var(--px-status-success-border)'
            : 'var(--px-brand-iris-border)',
          color: isPhotoUploadComplete
            ? 'var(--px-status-success-text)'
            : 'var(--px-brand-iris-active)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          {isPhotoUploadComplete ? (
            <Check size={16} strokeWidth={2} />
          ) : (
            <RefreshCw size={16} strokeWidth={2} className="animate-spin" />
          )}
          <span style={{ fontWeight: 600 }}>
            {isPhotoUploadComplete
              ? `${uploadedCount} Photos Verified & Color Harmonies Indexed`
              : `Indexing & Downsampling ${uploadedCount} Photos in Background...`}
          </span>
        </div>
        <span className="studio-status-meta">Guided Story Studio</span>
      </div>

      <div className="studio-header">
        <h2>Design Your Editorial Photobook</h2>
        <p>
          Configure your narrative direction, cover jacket typography, and inner
          spread layout density before synthesizing your three bespoke book
          editions.
        </p>
      </div>

      {/* Stage 1: Occasion Narrative & Category Chips */}
      <section className="studio-section">
        <div className="studio-section-header">
          <span className="studio-stage-Index">01</span>
          <div>
            <h3>Story &amp; Occasion Narrative</h3>
            <p>Describe the setting, people, or mood of your collection.</p>
          </div>
        </div>

        <div className="studio-pill-row">
          <span className="studio-pill-label">
            <Compass size={14} strokeWidth={1.75} />
            <span>Occasion Presets</span>
          </span>
          <div className="pill-container">
            {OCCASION_PILLS.map((pill) => {
              const active = selectedPill === pill;
              return (
                <button
                  key={pill}
                  type="button"
                  className={`pill-tag ${active ? 'active' : ''}`}
                  onClick={() => handleSelectPill(pill)}
                  disabled={isLoading}
                >
                  {pill}
                </button>
              );
            })}
          </div>
        </div>

        <textarea
          className="studio-textarea"
          rows={2}
          value={promptInput}
          onChange={handlePromptChange}
          placeholder="Describe your story or occasion (e.g., Summer coastal road trip along Big Sur with family)..."
          disabled={isLoading}
        />
      </section>

      {/* Stage 2: Cover Title Studio */}
      <section className="studio-section">
        <div className="studio-section-header" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
            <span className="studio-stage-Index">02</span>
            <div>
              <h3>Cover Title Studio</h3>
              <p>Brainstorm editorial titles with AI or enter your own jacket title.</p>
            </div>
          </div>

          <button
            type="button"
            className="btn btn-secondary studio-ai-btn"
            onClick={handleSuggestTitles}
            disabled={isLoading || isSuggestingTitles}
          >
            {isSuggestingTitles ? (
              <RefreshCw size={15} strokeWidth={1.75} className="animate-spin" />
            ) : (
              <Sparkles size={15} strokeWidth={1.75} color="var(--px-brand-iris)" />
            )}
            <span>{isSuggestingTitles ? 'Curating Titles...' : 'Generate AI Titles'}</span>
          </button>
        </div>

        {/* Shimmer Loading State */}
        {isSuggestingTitles && (
          <div className="studio-title-grid">
            {[0, 1, 2, 3].map((n) => (
              <div key={n} className="px-shimmer-card" />
            ))}
          </div>
        )}

        {/* 4 Selectable AI Title Cards */}
        {!isSuggestingTitles && suggestions && suggestions.titles && (
          <div className="studio-title-grid">
            {suggestions.titles.slice(0, 4).map((title, idx) => {
              const sub =
                (suggestions.subtitles &&
                  suggestions.subtitles[idx % suggestions.subtitles.length]) ||
                'A COLLECTION OF MEMORIES';
              const isSelected = selectedTitleIdx === idx;
              return (
                <button
                  key={idx}
                  type="button"
                  className={`studio-title-card ${isSelected ? 'selected' : ''}`}
                  onClick={() => handlePickSuggestedCard(idx)}
                >
                  <div className="studio-title-card-top">
                    <Type size={14} strokeWidth={1.75} color="var(--px-brand-iris)" />
                    {isSelected && (
                      <span className="studio-card-check">
                        <Check size={12} strokeWidth={2.5} />
                      </span>
                    )}
                  </div>
                  <div className="studio-title-card-main">{title}</div>
                  <div className="studio-title-card-sub">{sub}</div>
                </button>
              );
            })}
          </div>
        )}

        {/* Custom Title & Subtitle Inline Fields */}
        <div className="studio-custom-title-row">
          <div className="studio-input-group">
            <label>
              <Edit3 size={13} strokeWidth={1.75} />
              <span>Custom Cover Title</span>
            </label>
            <input
              type="text"
              className="studio-input"
              value={customTitle}
              onChange={handleCustomTitleInput}
              placeholder="Enter custom cover title (optional)..."
              disabled={isLoading}
            />
          </div>
          <div className="studio-input-group">
            <label>
              <Type size={13} strokeWidth={1.75} />
              <span>Cover Subtitle</span>
            </label>
            <input
              type="text"
              className="studio-input"
              value={customSubtitle}
              onChange={handleCustomSubtitleInput}
              placeholder="e.g., AUTUMN 2026 • ARCHIVE EDITION"
              disabled={isLoading}
            />
          </div>
        </div>
      </section>

      {/* Stage 3: Layout Content Mode */}
      <section className="studio-section">
        <div className="studio-section-header">
          <span className="studio-stage-Index">03</span>
          <div>
            <h3>Inner Spread Layout Mode</h3>
            <p>Choose whether inner pages include editorial story captions or pure photography.</p>
          </div>
        </div>

        <div className="studio-mode-grid">
          <button
            type="button"
            className={`studio-mode-card ${includeText ? 'selected' : ''}`}
            onClick={() => setIncludeText(true)}
            disabled={isLoading}
          >
            <div className="studio-mode-icon">
              <BookOpen size={18} strokeWidth={1.75} />
            </div>
            <div className="studio-mode-body">
              <div className="studio-mode-title">
                <span>Include Narrative Captions</span>
                {includeText && <Check size={15} strokeWidth={2.25} color="var(--px-brand-iris)" />}
              </div>
              <p>
                Pairs chapter openers and curated story captions alongside your photographs.
              </p>
            </div>
          </button>

          <button
            type="button"
            className={`studio-mode-card ${!includeText ? 'selected' : ''}`}
            onClick={() => setIncludeText(false)}
            disabled={isLoading}
          >
            <div className="studio-mode-icon">
              <Image size={18} strokeWidth={1.75} />
            </div>
            <div className="studio-mode-body">
              <div className="studio-mode-title">
                <span>Photo-Only Layouts (No Text)</span>
                {!includeText && <Check size={15} strokeWidth={2.25} color="var(--px-brand-iris)" />}
              </div>
              <p>
                Allocates 100% of every inner spread exclusively to photography with zero text slots.
              </p>
            </div>
          </button>
        </div>

        {includeText && (
          <label
            className="studio-vision-optin"
            style={{
              display: 'flex',
              gap: '10px',
              alignItems: 'flex-start',
              marginTop: '14px',
              cursor: isLoading ? 'default' : 'pointer'
            }}
          >
            <input
              type="checkbox"
              checked={usePhotoVision}
              onChange={(e) => setUsePhotoVision(e.target.checked)}
              disabled={isLoading}
              style={{ marginTop: '3px', accentColor: 'var(--px-brand-iris)' }}
            />
            <span>
              <strong>Let AI look at a few of my photos to write captions</strong>
              <br />
              <small style={{ opacity: 0.75 }}>
                About 3 photos per chapter are sent to Google Gemini. Off by default.
              </small>
            </span>
          </label>
        )}
      </section>

      {/* Stage 4: Summary Review & Launch Action */}
      <section className="studio-launch-bar">
        <div className="studio-summary-meta">
          <div className="studio-summary-item">
            <span className="studio-summary-label">Cover Jacket</span>
            <span className="studio-summary-value">{displayTitlePreview}</span>
          </div>
          <div className="studio-summary-divider" />
          <div className="studio-summary-item">
            <span className="studio-summary-label">Subtitle</span>
            <span className="studio-summary-value">{displaySubtitlePreview}</span>
          </div>
          <div className="studio-summary-divider" />
          <div className="studio-summary-item">
            <span className="studio-summary-label">Inner Spreads</span>
            <span className="studio-summary-badge">
              {includeText
                ? usePhotoVision
                  ? 'Narrative Captions · AI reads photos'
                  : 'Narrative Captions'
                : 'Photo-Only (Zero Text)'}
            </span>
          </div>
        </div>

        <button
          type="button"
          className="btn btn-primary studio-launch-btn"
          onClick={handleLaunchGeneration}
          disabled={isLoading}
        >
          <Sparkles size={16} strokeWidth={1.75} />
          <span>Generate Photobook Variations</span>
          <ArrowRight size={16} strokeWidth={1.75} />
        </button>
      </section>
    </div>
  );
}
