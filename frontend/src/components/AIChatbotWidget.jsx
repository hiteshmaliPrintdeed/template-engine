import React, { useState, useRef, useEffect } from 'react';
import {
  Sparkles,
  Type,
  BookOpen,
  Image as ImageIcon,
  Check,
  ArrowUp,
  RefreshCw,
  Compass,
  Heart,
  Users,
  Sun,
  Calendar,
  UploadCloud,
  Plus,
  X
} from 'lucide-react';
import PixovoClientDownsampler from '../utils/client_downsampler';
import PhotoFrame from './PhotoFrame';
import { useToast } from './Toast';

const OCCASION_CARDS = [
  {
    id: 'trip',
    title: 'My last trip',
    subtitle: 'Road trips, vacations & scenic adventures',
    prompt: 'My last trip',
    gradient: 'linear-gradient(135deg, #0BA28D 0%, #4BB8C4 100%)',
    Icon: Compass
  },
  {
    id: 'gift',
    title: 'A heartfelt gift',
    subtitle: 'Celebrations, tributes & keepsakes',
    prompt: 'A heartfelt gift for someone special',
    gradient: 'linear-gradient(135deg, #D98A86 0%, #EAA8A4 100%)',
    Icon: Heart
  },
  {
    id: 'family',
    title: 'Family milestones',
    subtitle: 'Holidays, reunions & everyday joy',
    prompt: 'Family holiday and milestones',
    gradient: 'linear-gradient(135deg, #E5B438 0%, #F2C94C 100%)',
    Icon: Users
  },
  {
    id: 'wedding',
    title: 'Wedding & love',
    subtitle: 'Ceremonies, vows & romantic memories',
    prompt: 'Wedding celebration and love story',
    gradient: 'linear-gradient(135deg, #032A2A 0%, #0BA28D 100%)',
    Icon: Sparkles
  },
  {
    id: 'year',
    title: 'Year in review',
    subtitle: 'Highlights from a whole year together',
    prompt: 'Our year in review — favorite memories',
    gradient: 'linear-gradient(135deg, #5C8E64 0%, #94AC93 100%)',
    Icon: Calendar
  },
  {
    id: 'weekend',
    title: 'Weekend getaway',
    subtitle: 'Short escapes with friends & family',
    prompt: 'Weekend getaway adventure',
    gradient: 'linear-gradient(135deg, #4BB8C4 0%, #94AC93 100%)',
    Icon: Sun
  }
];

const FOLLOWUP_CHIPS = [
  'With family & kids',
  'With my partner',
  'With close friends',
  'Scenic views & landmarks',
  'Candid moments & laughter',
  'Warm & nostalgic vibe'
];

export default function AIChatbotWidget({
  userPrompt,
  setUserPrompt,
  onGenerate,
  onPhotosUploaded,
  reconciledPhotos = [],
  ingestProgress = { done: 0, total: 0, received: 0, survived: 0 },
  isPhotoUploadComplete,
  uploadedCount,
  isLoading,
  isWaitingForIngest = false,
  sessionId
}) {
  const toast = useToast();

  // Conversational messages list: [{ id, role: 'user' | 'ai', text }]
  const [messages, setMessages] = useState(() => {
    if (userPrompt && userPrompt.trim()) {
      return [
        { id: 'init-user', role: 'user', text: userPrompt.trim() },
        {
          id: 'init-ai',
          role: 'ai',
          text: "That sounds like a wonderful book! Tell me a little more about the setting, who was there, or any special moments you'd like to highlight."
        }
      ];
    }
    return [];
  });

  const [chatInput, setChatInput] = useState('');
  const [selectedChips, setSelectedChips] = useState([]);
  const [isSuggestingTitles, setIsSuggestingTitles] = useState(false);
  const [suggestions, setSuggestions] = useState(null);
  const [selectedTitleIdx, setSelectedTitleIdx] = useState(null);
  const [customTitle, setCustomTitle] = useState('');
  const [customSubtitle, setCustomSubtitle] = useState('');
  const [includeText, setIncludeText] = useState(true);
  // Opt-in, off by default: only when ticked are a few photos sent to Gemini.
  const [usePhotoVision, setUsePhotoVision] = useState(false);

  // Local worker downsampling states
  const [isDownsampling, setIsDownsampling] = useState(false);
  const [downsampleStats, setDownsampleStats] = useState({ completed: 0, total: 0 });
  const [dragActive, setDragActive] = useState(false);
  const [isPhotoModalOpen, setIsPhotoModalOpen] = useState(false);

  const fileInputRef = useRef(null);
  const threadEndRef = useRef(null);
  const downsamplerRef = useRef(null);

  if (!downsamplerRef.current) {
    downsamplerRef.current = new PixovoClientDownsampler({
      maxDimension: 512,
      quality: 0.85
    });
  }

  useEffect(() => {
    return () => {
      downsamplerRef.current?.terminate();
    };
  }, []);

  // Determine if user has entered the active conversational thread
  const hasStartedStory =
    messages.length > 0 || uploadedCount > 0 || isDownsampling || reconciledPhotos.length > 0;

  // Build combined narrative prompt from user messages + selected chips
  const computeEffectivePrompt = (msgs = messages, chips = selectedChips) => {
    const userTexts = msgs.filter((m) => m.role === 'user').map((m) => m.text);
    const base = userTexts.join(' — ');
    const chipStr = chips.length > 0 ? ` (${chips.join(', ')})` : '';
    return (base + chipStr).trim() || userPrompt || 'Cherished Memories';
  };

  const generateContextualReply = (text, currentTurnCount) => {
    const lower = text.toLowerCase();
    if (currentTurnCount === 0) {
      if (
        lower.includes('trip') ||
        lower.includes('vacation') ||
        lower.includes('travel') ||
        lower.includes('getaway')
      ) {
        return "I'd love to help you capture that journey! Where did you travel, who joined you, and what were your favorite moments?";
      }
      if (lower.includes('gift') || lower.includes('heartfelt')) {
        return 'A custom photo book makes an unforgettable keepsake. Who is this book for, and what memories or message are you celebrating?';
      }
      if (lower.includes('wedding') || lower.includes('love')) {
        return 'Congratulations! Tell me about the celebration — the setting, the atmosphere, or the moments that meant the most.';
      }
      if (lower.includes('family') || lower.includes('milestone')) {
        return 'Family stories are timeless. Which milestones, traditions, or everyday moments are we bringing together in this book?';
      }
      return 'That sounds like a wonderful story! Tell me a little more — who was there, where did it take place, or what mood should the book have?';
    }
    return "Got it — I've woven those details into your story direction. You can keep adding notes below, manage your photos, or tap 'Start creating my book' whenever you're ready.";
  };

  const handleStartWithOccasion = (card) => {
    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: card.title };
    const aiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      text: generateContextualReply(card.title, messages.length)
    };
    const nextMsgs = [...messages, userMsg, aiMsg];
    setMessages(nextMsgs);
    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);
  };

  const handleSendMessage = (e) => {
    if (e) e.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed) return;

    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: trimmed };
    const aiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      text: generateContextualReply(trimmed, messages.length)
    };
    const nextMsgs = [...messages, userMsg, aiMsg];
    setMessages(nextMsgs);
    setChatInput('');

    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);

    setTimeout(() => {
      threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 80);
  };

  const handleToggleFollowupChip = (chip) => {
    const exists = selectedChips.includes(chip);
    const nextChips = exists
      ? selectedChips.filter((c) => c !== chip)
      : [...selectedChips, chip];
    setSelectedChips(nextChips);
    const nextPrompt = computeEffectivePrompt(messages, nextChips);
    setUserPrompt(nextPrompt);
  };

  // Handle file selection & 512px Web Worker downsampling inline inside Story Mode
  const handleFilesSelected = async (files) => {
    if (!files || files.length === 0) return;
    const fileList = Array.from(files).filter(
      (f) => f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|tiff)$/i.test(f.name)
    );

    if (fileList.length === 0) {
      toast.show({
        title: 'Unsupported file format',
        message: 'Please select valid image files (JPEG, PNG, or WebP).',
        tone: 'warning'
      });
      return;
    }

    // If user jumped straight to uploading photos before picking an occasion, add a welcoming turn
    if (messages.length === 0) {
      setMessages([
        {
          id: `u-photos-${Date.now()}`,
          role: 'user',
          text: `Added ${fileList.length} photos to start my book`
        },
        {
          id: `a-photos-${Date.now() + 1}`,
          role: 'ai',
          text: "Wonderful! While your photos are being curated, tell me a little about the story behind them — what's the occasion or mood?"
        }
      ]);
    }

    setIsDownsampling(true);
    setDownsampleStats({ completed: 0, total: fileList.length });

    const startTime = performance.now();
    try {
      const downsampler = downsamplerRef.current;
      const processedResults = await downsampler.processBatch(fileList, (completed, total) => {
        setDownsampleStats({ completed, total });
      });

      if (!processedResults || processedResults.length === 0) {
        throw new Error('None of the selected files could be decoded as images.');
      }

      const totalDownsampleTimeMs = performance.now() - startTime;
      const previewItems = processedResults.map((p) => ({
        photo_id: p.photo_id,
        filename: p.filename,
        aspect_ratio: p.aspect_ratio,
        previewUrl: p.thumbnail_blob ? URL.createObjectURL(p.thumbnail_blob) : '',
        originalFile: p.original_file,
        thumbnailBlob: p.thumbnail_blob
      }));

      setIsDownsampling(false);

      if (onPhotosUploaded) {
        onPhotosUploaded({
          processedCount: processedResults.length,
          processedPhotos: processedResults,
          previewItems,
          downsampler,
          downsampleTimeMs: totalDownsampleTimeMs
        });
      }
    } catch (err) {
      console.error('[StoryMode] Downsampling error:', err);
      setIsDownsampling(false);
      toast.show({
        title: 'Photo processing failed',
        message: err.message || 'Could not process the selected images. Please try another batch.',
        tone: 'error'
      });
    }
  };

  const handleFileInputChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFilesSelected(e.target.files);
      e.target.value = '';
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFilesSelected(e.dataTransfer.files);
    }
  };

  const triggerFilePicker = () => {
    fileInputRef.current?.click();
  };

  const handleSuggestTitles = async () => {
    const query = computeEffectivePrompt();
    setIsSuggestingTitles(true);
    try {
      const res = await fetch('/api/chat/suggest-titles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_prompt: query,
          photo_count: uploadedCount || reconciledPhotos.length || 0,
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

  const handleLaunchBookCreation = () => {
    if (uploadedCount === 0 && reconciledPhotos.length === 0 && !isDownsampling) {
      toast.show({
        title: 'Add your photos first',
        message: 'Select the photos you want in your book so we can design your pages.',
        tone: 'info'
      });
      triggerFilePicker();
      return;
    }

    const effectivePrompt = computeEffectivePrompt();
    setUserPrompt(effectivePrompt);

    onGenerate(effectivePrompt, {
      custom_title: customTitle.trim() || null,
      include_text: includeText,
      subtitle: customSubtitle.trim() || null,
      // Meaningless without captions, so never sent as true for photo-only books.
      use_photo_vision: includeText && usePhotoVision
    });
  };

  // Calculate inline upload numbers for Story Mode strip
  const totalCount = isDownsampling
    ? downsampleStats.total
    : uploadedCount || reconciledPhotos.length;
  const completedCount = isDownsampling
    ? downsampleStats.completed
    : isPhotoUploadComplete
    ? totalCount
    : ingestProgress.received || 0;
  const survivedCount =
    ingestProgress.survived ||
    reconciledPhotos.filter((p) => p.status !== 'rejected').length;
  const uploadPct =
    totalCount > 0
      ? Math.min(100, Math.round((completedCount / Math.max(1, totalCount)) * 100))
      : 0;

  const inlineStripThumbs = reconciledPhotos.slice(0, 8);
  const shimmerPlaceholderCount =
    !isPhotoUploadComplete || isDownsampling
      ? Math.max(2, Math.min(4, totalCount - inlineStripThumbs.length))
      : 0;

  return (
    <div
      className="mx-story-shell"
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
    >
      {/* Hidden File Input for Inline Story Mode Photo Selection */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*"
        onChange={handleFileInputChange}
        style={{ display: 'none' }}
        disabled={isLoading || isDownsampling}
      />

      {/* =================================================================
          SCREEN 1: WARM STORY MODE WELCOME (Before Prompt or Photos)
          ================================================================= */}
      {!hasStartedStory && (
        <>
          <div className="mx-welcome-hero">
            <span className="mx-welcome-eyebrow">
              <Sparkles size={13} strokeWidth={2.2} />
              <span>Welcome to Story Mode</span>
            </span>
            <h1 className="mx-welcome-title">What book are you creating today?</h1>
            <p className="mx-welcome-subtitle">
              Pick a story theme below, describe your memories in your own words, or drop your photos right in.
            </p>
          </div>

          <div className="mx-occasion-dock-section">
            <div className="mx-occasion-grid">
              {OCCASION_CARDS.map((card, idx) => {
                const IconComponent = card.Icon;
                const staggerClass = `warm-stagger-${Math.min(6, idx + 1)}`;
                return (
                  <button
                    key={card.id}
                    type="button"
                    className={`mx-occasion-card ${staggerClass}`}
                    onClick={() => handleStartWithOccasion(card)}
                  >
                    <div
                      className="mx-occasion-thumb"
                      style={{ background: card.gradient }}
                    >
                      <IconComponent size={23} strokeWidth={1.9} color="#ffffff" />
                    </div>
                    <div className="mx-occasion-card-body">
                      <span className="mx-occasion-card-title">{card.title}</span>
                      <span className="mx-occasion-card-sub">{card.subtitle}</span>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Warm Quick-Upload Banner right below Occasion Cards */}
            <div
              className="mx-inline-upload-card warm-stagger-6"
              onClick={triggerFilePicker}
              style={{
                marginTop: '0.95rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '1rem',
                flexWrap: 'wrap',
                background: dragActive ? 'var(--px-brand-iris-subtle)' : 'rgba(255, 253, 249, 0.94)',
                borderStyle: dragActive ? 'solid' : 'dashed',
                borderColor: dragActive ? 'var(--px-brand-iris)' : 'var(--px-brand-iris-border)'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                <div
                  style={{
                    width: '42px',
                    height: '42px',
                    borderRadius: '12px',
                    background: 'var(--px-brand-iris-subtle)',
                    border: '1px solid var(--px-brand-iris-border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0
                  }}
                >
                  <UploadCloud size={20} color="var(--px-brand-iris)" strokeWidth={1.9} />
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.92rem', color: 'var(--px-text-primary)' }}>
                    Have your photos ready? Start by selecting or dropping them here
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--px-text-muted)' }}>
                    Supports 20 to 1,000 photos • Smart blur &amp; duplicate filtering
                  </div>
                </div>
              </div>

              <span className="mx-chip-btn" style={{ color: 'var(--px-brand-iris)', borderColor: 'var(--px-brand-iris-border)' }}>
                <Plus size={14} style={{ marginRight: '4px' }} />
                Select Photos
              </span>
            </div>
          </div>
        </>
      )}

      {/* =================================================================
          SCREEN 2: CONVERSATIONAL THREAD + INLINE UPLOAD & STYLE
          ================================================================= */}
      {hasStartedStory && (
        <div className="mx-chat-thread">
          {/* Render User & AI Conversation Turns */}
          {messages.map((msg, idx) => {
            if (msg.role === 'user') {
              return (
                <div key={msg.id || idx} className="mx-user-bubble-row">
                  <div className="mx-user-bubble">{msg.text}</div>
                </div>
              );
            }
            return (
              <div key={msg.id || idx} className="mx-ai-turn">
                <span className="mx-ai-badge">
                  <Sparkles size={12} strokeWidth={2.2} />
                  Story Companion
                </span>
                <p className="mx-ai-text">{msg.text}</p>

                {/* Show Quick-Reply Story Details Chips under the first AI turn */}
                {idx === 1 && (
                  <div className="mx-Quick-chips">
                    {FOLLOWUP_CHIPS.map((chip) => {
                      const active = selectedChips.includes(chip);
                      return (
                        <button
                          key={chip}
                          type="button"
                          className={`mx-chip-btn ${active ? 'active' : ''}`}
                          onClick={() => handleToggleFollowupChip(chip)}
                        >
                          {active && (
                            <Check
                              size={13}
                              strokeWidth={2.5}
                              style={{ marginRight: '5px', verticalAlign: '-2px' }}
                            />
                          )}
                          {chip}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          {/* Inline Photo Upload Turn */}
          <div className="mx-ai-turn">
            <span className="mx-ai-badge">
              <ImageIcon size={12} strokeWidth={2.2} />
              Photo Curation
            </span>
            <p className="mx-ai-text">
              {totalCount === 0
                ? "Now let's bring your photos into the story. Select up to 1,000 photos — we'll automatically filter out blurry shots and duplicates."
                : isPhotoUploadComplete && !isDownsampling
                ? `Great — your ${survivedCount} curated photos are ready! Tap Manage Photos anytime to review or add more.`
                : 'Great — your photos are uploading and being curated. Tap Manage Photos to view them.'}
            </p>

            {/* State A: 0 photos uploaded yet -> Inline Dropzone Card */}
            {totalCount === 0 && !isDownsampling && (
              <div
                className="mx-inline-upload-card"
                onClick={triggerFilePicker}
                style={{
                  cursor: 'pointer',
                  borderStyle: dragActive ? 'solid' : 'dashed',
                  borderColor: dragActive ? 'var(--px-brand-iris)' : 'var(--px-brand-iris-border)',
                  textAlign: 'center',
                  padding: '1.65rem 1.25rem'
                }}
              >
                <UploadCloud
                  size={34}
                  color="var(--px-brand-iris)"
                  strokeWidth={1.75}
                  style={{ margin: '0 auto 0.55rem' }}
                />
                <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--px-text-primary)', marginBottom: '0.25rem' }}>
                  Tap to select photos, or drag &amp; drop here
                </div>
                <div style={{ fontSize: '0.84rem', color: 'var(--px-text-secondary)' }}>
                  Fast 512px client-side curation • Supports JPEG, PNG, WebP
                </div>
              </div>
            )}

            {/* State B: Photos Downsampling or Uploading/Ready -> Inline Thumbnail Strip */}
            {(totalCount > 0 || isDownsampling) && (
              <div className="mx-inline-upload-card">
                <div className="mx-inline-upload-header">
                  <span className="mx-inline-upload-title">
                    {isDownsampling ? (
                      <>
                        <RefreshCw size={15} className="animate-spin" color="var(--px-brand-iris)" />
                        <span>
                          Preparing your photos ({downsampleStats.completed}/{downsampleStats.total})...
                        </span>
                      </>
                    ) : !isPhotoUploadComplete ? (
                      <>
                        <RefreshCw size={15} className="animate-spin" color="var(--px-brand-iris)" />
                        <span>
                          Uploading your photos ({completedCount}/{totalCount})...
                        </span>
                      </>
                    ) : (
                      <>
                        <Check size={16} strokeWidth={2.5} color="var(--px-status-success-text)" />
                        <span>
                          {survivedCount} photos curated &amp; ready ({totalCount} scanned)
                        </span>
                      </>
                    )}
                  </span>

                  <button
                    type="button"
                    className="mx-chip-btn"
                    style={{ padding: '0.35rem 0.85rem', fontSize: '0.78rem' }}
                    onClick={() => setIsPhotoModalOpen(true)}
                  >
                    Manage Photos
                  </button>
                </div>

                {/* Horizontal Square Thumbnail Strip + Warm Shimmer Placeholders */}
                <div className="mx-inline-photo-strip">
                  {inlineStripThumbs.map((item) => (
                    <div
                      key={item.photo_id}
                      className={`mx-inline-photo-thumb ${item.status === 'rejected' ? 'rejected' : ''}`}
                      onClick={() => setIsPhotoModalOpen(true)}
                      title={item.filename}
                    >
                      <PhotoFrame
                        src={item.url}
                        aspectRatio={1}
                        dominantColors={item.dominant_colors}
                        alt={item.filename}
                        style={{ width: '100%', height: '100%' }}
                      />
                    </div>
                  ))}

                  {Array.from({ length: shimmerPlaceholderCount }).map((_, sIdx) => (
                    <div key={`shimmer-${sIdx}`} className="mx-inline-photo-shimmer" />
                  ))}

                  {reconciledPhotos.length > inlineStripThumbs.length && (
                    <button
                      type="button"
                      onClick={() => setIsPhotoModalOpen(true)}
                      style={{
                        width: '68px',
                        height: '68px',
                        borderRadius: '11px',
                        border: '1px solid var(--px-brand-iris-border)',
                        background: 'var(--px-brand-iris-subtle)',
                        color: 'var(--px-brand-iris)',
                        fontWeight: 700,
                        fontSize: '0.84rem',
                        flexShrink: 0,
                        cursor: 'pointer'
                      }}
                    >
                      +{reconciledPhotos.length - inlineStripThumbs.length}
                    </button>
                  )}
                </div>

                {/* Progress Bar */}
                {(!isPhotoUploadComplete || isDownsampling) && (
                  <div className="mx-inline-progress-bar">
                    <div
                      className="mx-inline-progress-fill"
                      style={{ width: `${Math.max(8, uploadPct)}%` }}
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Turn 3: Inline Story Style, Cover Title & "Start creating my book" CTA */}
          <div className="mx-ai-turn">
            <span className="mx-ai-badge">
              <BookOpen size={12} strokeWidth={2.2} />
              Editorial Styling
            </span>
            <p className="mx-ai-text">
              How should we style your pages and cover? Choose your storytelling preference below, then tap{' '}
              <strong>Start creating my book</strong> to reveal 3 custom editions.
            </p>

            {/* 2 Storytelling Style Cards */}
            <div className="mx-style-options-grid">
              <button
                type="button"
                className={`mx-style-option-card ${includeText ? 'selected' : ''}`}
                onClick={() => setIncludeText(true)}
                disabled={isLoading}
              >
                <div className="mx-style-option-title">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                    <BookOpen size={16} color="var(--px-brand-iris)" />
                    Storytelling Captions
                  </span>
                  {includeText && <Check size={16} strokeWidth={2.5} color="var(--px-brand-iris)" />}
                </div>
                <div className="mx-style-option-desc">
                  Pairs AI-crafted chapter headers and warm narrative captions alongside your photos.
                </div>
              </button>

              <button
                type="button"
                className={`mx-style-option-card ${!includeText ? 'selected' : ''}`}
                onClick={() => setIncludeText(false)}
                disabled={isLoading}
              >
                <div className="mx-style-option-title">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                    <ImageIcon size={16} color="var(--px-brand-iris)" />
                    Clean Photo-Forward
                  </span>
                  {!includeText && <Check size={16} strokeWidth={2.5} color="var(--px-brand-iris)" />}
                </div>
                <div className="mx-style-option-desc">
                  Dedicates 100% of every inner spread to photography with zero text boxes.
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
                  marginTop: '0.75rem',
                  padding: '0.75rem 1rem',
                  background: 'rgba(255, 255, 255, 0.7)',
                  border: '1px solid var(--px-border-light)',
                  borderRadius: '12px',
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
                <span style={{ fontSize: '0.85rem', color: 'var(--px-text-primary)' }}>
                  <strong>Let AI look at a few of my photos to write captions</strong>
                  <br />
                  <small style={{ color: 'var(--px-text-secondary)', fontSize: '0.78rem' }}>
                    About 3 photos per chapter are sent to Google Gemini. Off by default.
                  </small>
                </span>
              </label>
            )}

            {/* Optional AI Cover Title Card */}
            <div
              style={{
                marginTop: '0.75rem',
                background: '#ffffff',
                border: '1px solid var(--px-border-light)',
                borderRadius: '16px',
                padding: '1rem 1.15rem',
                boxShadow: 'var(--px-shadow-sm)'
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '0.75rem',
                  flexWrap: 'wrap',
                  marginBottom: '0.75rem'
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.45rem',
                    fontWeight: 700,
                    fontSize: '0.9rem',
                    color: 'var(--px-text-primary)'
                  }}
                >
                  <Type size={15} color="var(--px-brand-iris)" />
                  <span>Book Cover Title</span>
                </div>

                <button
                  type="button"
                  className="mx-chip-btn"
                  style={{ padding: '0.35rem 0.85rem', fontSize: '0.8rem', fontWeight: 600 }}
                  onClick={handleSuggestTitles}
                  disabled={isLoading || isSuggestingTitles}
                >
                  {isSuggestingTitles ? (
                    <>
                      <RefreshCw size={13} className="animate-spin" style={{ marginRight: '5px' }} />
                      Suggesting...
                    </>
                  ) : (
                    <>
                      <Sparkles size={13} color="var(--px-brand-iris)" style={{ marginRight: '5px' }} />
                      Suggest AI Titles
                    </>
                  )}
                </button>
              </div>

              {!isSuggestingTitles && suggestions && suggestions.titles && (
                <div className="mx-Quick-chips" style={{ marginBottom: '0.75rem' }}>
                  {suggestions.titles.slice(0, 4).map((title, idx) => {
                    const isSelected = selectedTitleIdx === idx;
                    return (
                      <button
                        key={idx}
                        type="button"
                        className={`mx-chip-btn ${isSelected ? 'active' : ''}`}
                        onClick={() => handlePickSuggestedCard(idx)}
                      >
                        {title}
                      </button>
                    );
                  })}
                </div>
              )}

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                  gap: '0.65rem'
                }}
              >
                <input
                  type="text"
                  className="studio-input"
                  value={customTitle}
                  onChange={(e) => {
                    setSelectedTitleIdx(null);
                    setCustomTitle(e.target.value);
                  }}
                  placeholder="Cover title (or leave blank for AI)..."
                  disabled={isLoading}
                />
                <input
                  type="text"
                  className="studio-input"
                  value={customSubtitle}
                  onChange={(e) => setCustomSubtitle(e.target.value)}
                  placeholder="Optional subtitle (e.g. SUMMER 2026)..."
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Warm Sunlit Signature CTA Button */}
            <div
              style={{
                marginTop: '1.15rem',
                display: 'flex',
                alignItems: 'center',
                gap: '1rem',
                flexWrap: 'wrap'
              }}
            >
              <button
                type="button"
                className="mx-btn-story-mode"
                onClick={handleLaunchBookCreation}
                disabled={isLoading || isWaitingForIngest || isDownsampling}
              >
                {isWaitingForIngest ? (
                  <>
                    <RefreshCw size={17} strokeWidth={2} className="animate-spin" />
                    <span>Finishing photo upload...</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={17} strokeWidth={2} />
                    <span>Start creating my book</span>
                  </>
                )}
              </button>

              {totalCount > 0 && (
                <span
                  style={{
                    fontSize: '0.82rem',
                    color: 'var(--px-text-secondary)',
                    fontWeight: 500
                  }}
                >
                  {isPhotoUploadComplete
                    ? `${survivedCount} curated photos ready`
                    : `Uploading (${completedCount}/${totalCount}) — you can tap Start anytime`}
                </span>
              )}
            </div>
          </div>

          <div ref={threadEndRef} />
        </div>
      )}

      {/* =================================================================
          STICKY BOTTOM WARM INPUT DOCK (Photos Pill + Input + Send Circle)
          ================================================================= */}
      <div className="mx-bottom-dock">
        <div className="mx-bottom-dock-inner">
          <button
            type="button"
            className="mx-photos-dock-btn"
            onClick={() => {
              if (totalCount > 0) {
                setIsPhotoModalOpen(true);
              } else {
                triggerFilePicker();
              }
            }}
            title="Upload or manage your book photos"
          >
            <ImageIcon size={17} strokeWidth={2} color="var(--px-brand-iris)" />
            <span>Photos</span>
            {totalCount > 0 && (
              <span className="mx-photos-count-badge">
                {isPhotoUploadComplete ? survivedCount : `${completedCount}/${totalCount}`}
              </span>
            )}
          </button>

          <form className="mx-input-pill-bar" onSubmit={handleSendMessage}>
            <input
              type="text"
              className="mx-input-field"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={
                hasStartedStory
                  ? 'Add more story details or notes...'
                  : 'Or tell us in your own words...'
              }
              disabled={isLoading}
            />
            <button
              type="submit"
              className="mx-send-circle-btn"
              disabled={!chatInput.trim() || isLoading}
              aria-label="Send message"
            >
              <ArrowUp size={18} strokeWidth={2.5} />
            </button>
          </form>
        </div>
      </div>

      {/* =================================================================
          PHOTO MANAGER DRAWER MODAL (When user taps "Photos")
          ================================================================= */}
      {isPhotoModalOpen && (
        <div className="mx-modal-backdrop" onClick={() => setIsPhotoModalOpen(false)}>
          <div className="mx-modal-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="mx-modal-header">
              <div>
                <h3
                  style={{
                    fontSize: '1.1rem',
                    fontWeight: 700,
                    color: 'var(--px-text-primary)'
                  }}
                >
                  Your Book Photos ({survivedCount} Kept / {totalCount} Total)
                </h3>
                <p style={{ fontSize: '0.82rem', color: 'var(--px-text-secondary)' }}>
                  {isPhotoUploadComplete
                    ? 'Smart quality curation complete. Dimmed photos were filtered for blur or duplication.'
                    : `Uploading & analysing quality (${completedCount} of ${totalCount})...`}
                </p>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ padding: '0.45rem 0.95rem', fontSize: '0.82rem' }}
                  onClick={() => {
                    setIsPhotoModalOpen(false);
                    triggerFilePicker();
                  }}
                >
                  <Plus size={15} />
                  <span>Replace / Add Batch</span>
                </button>
                <button
                  type="button"
                  className="mx-header-close-btn"
                  onClick={() => setIsPhotoModalOpen(false)}
                  aria-label="Close photo manager"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className="mx-modal-body">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(96px, 1fr))',
                  gap: '0.65rem'
                }}
              >
                {reconciledPhotos.map((item) => (
                  <div
                    key={item.photo_id}
                    className={`curation-tile curation-tile-${item.status}`}
                    style={{ width: '100%', height: '96px', borderRadius: '10px' }}
                    title={
                      item.status === 'rejected'
                        ? item.reject_reason || 'filtered'
                        : item.filename
                    }
                  >
                    <PhotoFrame
                      src={item.url}
                      aspectRatio={1}
                      dominantColors={item.dominant_colors}
                      alt={item.filename}
                      style={{ width: '100%', height: '100%', borderRadius: '10px' }}
                    />
                    {item.status === 'rejected' && (
                      <span className="curation-reject-tag">
                        {item.reject_reason || 'filtered'}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
