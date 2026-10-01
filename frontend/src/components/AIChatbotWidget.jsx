import React, { useState, useRef, useEffect } from 'react';
import {
  Sparkles,
  Type,
  BookOpen,
  Image as ImageIcon,
  Check,
  ArrowUp,
  ArrowRight,
  ArrowLeft,
  MessageSquare,
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
import ParallaxHeroImages from './ui/ParallaxHeroImages';
import PixovoClientDownsampler from '../utils/client_downsampler';
import PhotoFrame from './PhotoFrame';
import { useToast } from './Toast';
import '../styles/cosmic-stars.css';

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


const CURATED_HERO_IMAGES = [
  'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=600&q=80', // Tropical beach
  'https://images.unsplash.com/photo-1519741497674-611481863552?auto=format&fit=crop&w=600&q=80', // Wedding flowers & couple
  'https://images.unsplash.com/photo-1511895426328-dc8714191300?auto=format&fit=crop&w=600&q=80', // Warm family smiles
  'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=600&q=80', // Road trip journey
  'https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=600&q=80', // Mountain lake reflection
  'https://images.unsplash.com/photo-1511285560929-80b456fea0bc?auto=format&fit=crop&w=600&q=80', // Love & holding hands
  'https://images.unsplash.com/photo-1533105079780-92b9be482077?auto=format&fit=crop&w=600&q=80', // European historic street
  'https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=600&q=80', // Friends celebration
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
  const [heroStoryInput, setHeroStoryInput] = useState('');

  const heroParallaxImages = useMemo(() => {
    if (reconciledPhotos && reconciledPhotos.length > 0) {
      const userUrls = reconciledPhotos.filter((p) => p.url).map((p) => p.url);
      if (userUrls.length >= 8) return userUrls.slice(0, 8);
      return [...userUrls, ...CURATED_HERO_IMAGES].slice(0, 8);
    }
    return CURATED_HERO_IMAGES;
  }, [reconciledPhotos]);

  const handleHeroStorySubmit = (e) => {
    if (e) e.preventDefault();
    const trimmed = heroStoryInput.trim();
    if (!trimmed) return;

    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: trimmed };
    const aiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      text: generateContextualReply(trimmed, 0)
    };
    const nextMsgs = [userMsg, aiMsg];
    setMessages(nextMsgs);
    setUserPrompt(trimmed);
    setHeroStoryInput('');
  };
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
      className={hasStartedStory ? "mx-story-shell" : "mx-hero-shell-wrap"}
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
          SCREEN 1: PARALLAX HERO & DUAL ENTRY PATHWAYS
          ================================================================= */}
      {!hasStartedStory && (
        <div className="mx-hero-viewport">
          {/* Uiverse Cosmic Starfield Background */}
          <div className="cosmic-container">
            <div id="stars" />
            <div id="stars2" />
            <div id="stars3" />
          </div>

          {/* Floating 3D Parallax Images that respond to mouse physics */}
          <ParallaxHeroImages images={heroParallaxImages} />

          {/* Elevated Pixovo Editorial Centerpiece */}
          <div className="mx-hero-centerpiece">
            <span className="mx-welcome-eyebrow">
              <Sparkles size={14} strokeWidth={2.2} />
              <span>AI Photobook Creator • Made in USA</span>
            </span>

            <h1 className="mx-welcome-title">
              Create a Custom Photo Book Designed Automatically by AI.
            </h1>

            <p className="mx-welcome-subtitle">
              Turn your cherished moments into a beautifully printed photobook. Tell us your story, or drop your photos right in to begin.
            </p>

            {/* DUAL PATHWAY SELECTOR */}
            <div className="mx-hero-options-container">
              {/* PATHWAY 1: TELL ME ABOUT YOUR STORY */}
              <div className="mx-hero-path-card mx-hero-path-story">
                <div className="mx-hero-path-header">
                  <div
                    className="mx-hero-path-icon"
                    style={{ background: 'var(--px-brand-iris-subtle)', color: 'var(--px-brand-iris)' }}
                  >
                    <MessageSquare size={20} strokeWidth={2.1} />
                  </div>
                  <div>
                    <span
                      className="mx-hero-path-badge"
                      style={{ background: 'var(--px-brand-iris-subtle)', color: 'var(--px-brand-iris)' }}
                    >
                      Option 1
                    </span>
                    <h3 className="mx-hero-path-title">Tell me about your story</h3>
                  </div>
                </div>

                <p className="mx-hero-path-desc">
                  Describe your trip, loved ones, or memories in your own words. Our AI will craft personalized themes and chapter captions.
                </p>

                <form onSubmit={handleHeroStorySubmit} style={{ marginTop: 'auto' }}>
                  <div className="mx-hero-prompt-bar">
                    <input
                      type="text"
                      className="mx-hero-prompt-input"
                      placeholder="e.g. Summer family road trip along the coast..."
                      value={heroStoryInput}
                      onChange={(e) => setHeroStoryInput(e.target.value)}
                    />
                    <button
                      type="submit"
                      className="mx-hero-prompt-btn"
                      disabled={!heroStoryInput.trim()}
                      aria-label="Start Story"
                    >
                      <span>Continue</span>
                      <ArrowRight size={15} strokeWidth={2.5} />
                    </button>
                  </div>
                </form>

                <div className="mx-hero-chips-row">
                  <span className="mx-hero-chips-label">Quick Ideas:</span>
                  {OCCASION_CARDS.slice(0, 4).map((card) => (
                    <button
                      key={card.id}
                      type="button"
                      className="mx-hero-mini-chip"
                      onClick={() => handleStartWithOccasion(card)}
                    >
                      {card.title}
                    </button>
                  ))}
                </div>
              </div>

              {/* OR DIVIDER */}
              <div className="mx-hero-divider">
                <div className="mx-hero-divider-line" />
                <span className="mx-hero-divider-text">OR</span>
                <div className="mx-hero-divider-line" />
              </div>

              {/* PATHWAY 2: DROP YOUR PHOTOS */}
              <div
                className={`mx-hero-path-card mx-hero-path-photos ${dragActive ? 'drag-active' : ''}`}
                onClick={triggerFilePicker}
              >
                <div className="mx-hero-path-header">
                  <div
                    className="mx-hero-path-icon"
                    style={{ background: '#EDF8FA', color: '#0BA28D' }}
                  >
                    <UploadCloud size={22} strokeWidth={2.1} />
                  </div>
                  <div>
                    <span
                      className="mx-hero-path-badge"
                      style={{ background: '#EDF8FA', color: '#0BA28D' }}
                    >
                      Option 2
                    </span>
                    <h3 className="mx-hero-path-title">Drop your photos to begin</h3>
                  </div>
                </div>

                <p className="mx-hero-path-desc">
                  Already have photos ready? Drop them here to start instant quality filtering, duplicate removal, and layout synthesis.
                </p>

                <div className="mx-hero-drop-cta">
                  <span className="mx-btn-story-mode" style={{ padding: '0.68rem 1.45rem', fontSize: '0.9rem' }}>
                    <Plus size={16} strokeWidth={2.4} />
                    <span>Select Photos (20–1,000)</span>
                  </span>
                  <span style={{ fontSize: '0.78rem', color: 'var(--px-text-muted)' }}>
                    Drop files anywhere • JPEG, PNG, WebP
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* =================================================================
          SCREEN 2: UNIFIED COSMIC CHAT & PHOTO INGESTION INTERFACE
          ================================================================= */}
      {hasStartedStory && (
        <div className="mx-cosmic-story-shell">
          {/* Uiverse Cosmic Starfield Background */}
          <div className="cosmic-container">
            <div id="stars" />
            <div id="stars2" />
            <div id="stars3" />
          </div>

          {/* Top Stage Bar with Back navigation */}
          <div
            className="mx-chat-top-bar"
            style={{
              position: 'relative',
              zIndex: 10,
              maxWidth: '1200px',
              margin: '0 auto',
              width: '100%',
              padding: '1rem clamp(1rem, 3.5vw, 2.5rem) 0.5rem',
              borderBottom: '1px solid rgba(255, 255, 255, 0.1)'
            }}
          >
            <button
              type="button"
              className="mx-chat-back-btn"
              onClick={() => {
                setMessages([]);
                setHeroStoryInput('');
              }}
              title="Return to Story Mode Welcome Hero"
              style={{
                color: 'rgba(255, 255, 255, 0.85)',
                background: 'rgba(255, 255, 255, 0.08)',
                borderColor: 'rgba(255, 255, 255, 0.16)'
              }}
            >
              <ArrowLeft size={14} strokeWidth={2.4} />
              <span>Back to Story Selector</span>
            </button>
            <span
              className="mx-chat-stage-pill"
              style={{
                color: '#4BB8C4',
                background: 'rgba(75, 184, 196, 0.15)',
                borderColor: 'rgba(75, 184, 196, 0.35)'
              }}
            >
              <Sparkles size={11} strokeWidth={2.2} style={{ marginRight: '4px', verticalAlign: '-1px' }} />
              Story Mode · AI Cosmic Studio
            </span>
          </div>

          {/* Two-Column Cosmic Content Layout */}
          <div className="mx-cosmic-content-layout">
            {/* LEFT PANEL: AI Talking Indicator & Live Upload Radar */}
            <aside className="mx-cosmic-left-panel">
              {/* Uiverse-powered Pulsing AI Talking Loader with 4-Color Smooth Rainbow Transition */}
              <div
                className="pixovo-cosmic-loader-wrap"
                title="Pixovo AI Companion talking & analyzing"
              >
                <div className="pixovo-cosmic-halo" />
                <span className="loader" />
              </div>

              <div className="mx-cosmic-ai-badge">
                <Sparkles size={11} strokeWidth={2.2} />
                <span>AI Talking Companion</span>
              </div>

              <h3 className="mx-cosmic-ai-status-title">
                {isDownsampling
                  ? 'Curating Photos...'
                  : !isPhotoUploadComplete && totalCount > 0
                  ? 'Uploading & Analyzing...'
                  : isSuggestingTitles
                  ? 'Crafting Titles...'
                  : isLoading
                  ? 'Synthesizing Book...'
                  : 'AI Story Guide'}
              </h3>

              <p className="mx-cosmic-ai-status-sub">
                {isDownsampling
                  ? `Scanning & filtering duplicates (${downsampleStats.completed}/${downsampleStats.total})`
                  : !isPhotoUploadComplete && totalCount > 0
                  ? `Processing high-res memories (${completedCount}/${totalCount})`
                  : 'Listening to your story details and orchestrating your print edition.'}
              </p>

              {/* Photo Ingestion & Curation Mini Tracker */}
              <div className="mx-cosmic-upload-tracker">
                <div className="mx-cosmic-upload-header">
                  <span>Photo Status</span>
                  <span style={{ color: '#4BB8C4' }}>
                    {isPhotoUploadComplete && !isDownsampling && totalCount > 0
                      ? `${survivedCount} Ready`
                      : totalCount > 0
                      ? `${uploadPct}%`
                      : '0 Photos'}
                  </span>
                </div>

                <div className="mx-cosmic-progress-track">
                  <div
                    className="mx-cosmic-progress-fill"
                    style={{ width: `${Math.max(totalCount > 0 ? 8 : 0, uploadPct)}%` }}
                  />
                </div>

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: '0.2rem'
                  }}
                >
                  <span style={{ fontSize: '0.74rem', color: 'rgba(255, 255, 255, 0.6)' }}>
                    {totalCount > 0
                      ? `${completedCount}/${totalCount} scanned • ${survivedCount} curated`
                      : 'No photos selected yet'}
                  </span>
                  <button
                    type="button"
                    onClick={totalCount > 0 ? () => setIsPhotoModalOpen(true) : triggerFilePicker}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: '#4BB8C4',
                      fontSize: '0.74rem',
                      fontWeight: 700,
                      cursor: 'pointer',
                      textDecoration: 'underline'
                    }}
                  >
                    {totalCount > 0 ? 'Manage' : '+ Add Photos'}
                  </button>
                </div>

                {/* Mini Live Photo Strip in Left Panel */}
                {inlineStripThumbs.length > 0 && (
                  <div className="mx-cosmic-thumbs-strip">
                    {inlineStripThumbs.slice(0, 6).map((item) => (
                      <div
                        key={item.photo_id}
                        className="mx-cosmic-thumb-item"
                        onClick={() => setIsPhotoModalOpen(true)}
                        title={item.filename}
                        style={{ cursor: 'pointer' }}
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
                    {reconciledPhotos.length > 6 && (
                      <div
                        className="mx-cosmic-thumb-item"
                        onClick={() => setIsPhotoModalOpen(true)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          background: 'rgba(255, 255, 255, 0.1)',
                          color: '#ffffff',
                          fontSize: '0.74rem',
                          fontWeight: 700,
                          cursor: 'pointer'
                        }}
                      >
                        +{reconciledPhotos.length - 6}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </aside>

            {/* MAIN PANEL: Conversational Turns & Inner Customization */}
            <main className="mx-cosmic-main-panel">
              <div className="mx-cosmic-turns-box">
                {/* User & AI Conversation Turns */}
                {messages.map((msg, idx) => {
                  if (msg.role === 'user') {
                    return (
                      <div key={msg.id || idx} className="mx-cosmic-user-row">
                        <div className="mx-cosmic-user-bubble">{msg.text}</div>
                      </div>
                    );
                  }
                  return (
                    <div key={msg.id || idx} className="mx-cosmic-ai-row">
                      <div className="mx-cosmic-ai-head">
                        <Sparkles size={13} strokeWidth={2.4} />
                        <span>Story Companion</span>
                      </div>
                      <p className="mx-cosmic-ai-text">{msg.text}</p>
                    </div>
                  );
                })}

                {/* Inline Photo Ingestion Status in Main Flow */}
                <div className="mx-cosmic-ai-row">
                  <div className="mx-cosmic-ai-head">
                    <ImageIcon size={13} strokeWidth={2.4} />
                    <span>Photo Ingestion &amp; Curation</span>
                  </div>
                  <p className="mx-cosmic-ai-text">
                    {totalCount === 0
                      ? "Select up to 1,000 photos — our engine automatically removes blurs and duplicates while you describe your story."
                      : isPhotoUploadComplete && !isDownsampling
                      ? `All ${survivedCount} curated photos are ready! You can review them anytime or proceed to create your book.`
                      : `Uploading and analyzing photo quality (${completedCount} of ${totalCount})...`}
                  </p>

                  {/* Dropzone if 0 photos */}
                  {totalCount === 0 && !isDownsampling && (
                    <div
                      className="mx-inline-upload-card"
                      onClick={triggerFilePicker}
                      style={{
                        cursor: 'pointer',
                        border: '1.5px dashed rgba(255, 255, 255, 0.25)',
                        background: 'rgba(255, 255, 255, 0.04)',
                        textAlign: 'center',
                        padding: '1.5rem',
                        borderRadius: '16px'
                      }}
                    >
                      <UploadCloud size={32} color="#4BB8C4" style={{ margin: '0 auto 0.4rem' }} />
                      <div
                        style={{
                          fontWeight: 700,
                          fontSize: '0.96rem',
                          color: '#ffffff',
                          marginBottom: '0.2rem'
                        }}
                      >
                        Tap to add photos, or drop them anywhere
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'rgba(255, 255, 255, 0.6)' }}>
                        Fast 512px local worker curation • Supports JPEG, PNG, WebP
                      </div>
                    </div>
                  )}

                  {/* Thumbnail Strip if photos exist */}
                  {(totalCount > 0 || isDownsampling) && (
                    <div
                      style={{
                        background: 'rgba(255, 255, 255, 0.04)',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                        borderRadius: '16px',
                        padding: '1rem'
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          marginBottom: '0.75rem'
                        }}
                      >
                        <span style={{ fontSize: '0.84rem', fontWeight: 600, color: '#ffffff' }}>
                          {isDownsampling ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}>
                              <RefreshCw size={14} className="animate-spin" color="#4BB8C4" />
                              Preparing ({downsampleStats.completed}/{downsampleStats.total})...
                            </span>
                          ) : !isPhotoUploadComplete ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}>
                              <RefreshCw size={14} className="animate-spin" color="#4BB8C4" />
                              Uploading ({completedCount}/{totalCount})...
                            </span>
                          ) : (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}>
                              <Check size={15} color="#0BA28D" />
                              {survivedCount} photos curated &amp; ready ({totalCount} scanned)
                            </span>
                          )}
                        </span>
                        <button
                          type="button"
                          className="mx-cosmic-chip"
                          onClick={() => setIsPhotoModalOpen(true)}
                        >
                          Manage Photos
                        </button>
                      </div>

                      <div className="mx-cosmic-thumbs-strip">
                        {inlineStripThumbs.map((item) => (
                          <div
                            key={item.photo_id}
                            className="mx-cosmic-thumb-item"
                            onClick={() => setIsPhotoModalOpen(true)}
                            style={{ cursor: 'pointer', width: '56px', height: '56px' }}
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
                          <div
                            key={`shimmer-${sIdx}`}
                            className="mx-cosmic-thumb-item"
                            style={{
                              width: '56px',
                              height: '56px',
                              background:
                                'linear-gradient(90deg, rgba(255,255,255,0.05) 25%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0.05) 75%)',
                              backgroundSize: '200% 100%',
                              animation: 'pxShimmer 1.5s infinite linear'
                            }}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Editorial Styling & Cover Title Card */}
                <div className="mx-cosmic-card">
                  <div className="mx-cosmic-ai-head" style={{ marginBottom: '0.75rem' }}>
                    <BookOpen size={13} strokeWidth={2.4} />
                    <span>Editorial Styling</span>
                  </div>

                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                      gap: '0.75rem'
                    }}
                  >
                    <button
                      type="button"
                      className={`mx-cosmic-style-btn ${includeText ? 'selected' : ''}`}
                      onClick={() => setIncludeText(true)}
                      disabled={isLoading}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          fontWeight: 700,
                          fontSize: '0.92rem',
                          marginBottom: '0.3rem'
                        }}
                      >
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                          <BookOpen size={15} color="#4BB8C4" />
                          Storytelling Captions
                        </span>
                        {includeText && <Check size={15} strokeWidth={2.5} color="#0BA28D" />}
                      </div>
                      <div
                        style={{
                          fontSize: '0.8rem',
                          color: 'rgba(255, 255, 255, 0.7)',
                          lineHeight: 1.4
                        }}
                      >
                        Pairs AI-crafted chapter headers and narrative captions alongside your photos.
                      </div>
                    </button>

                    <button
                      type="button"
                      className={`mx-cosmic-style-btn ${!includeText ? 'selected' : ''}`}
                      onClick={() => setIncludeText(false)}
                      disabled={isLoading}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          fontWeight: 700,
                          fontSize: '0.92rem',
                          marginBottom: '0.3rem'
                        }}
                      >
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                          <ImageIcon size={15} color="#4BB8C4" />
                          Clean Photo-Forward
                        </span>
                        {!includeText && <Check size={15} strokeWidth={2.5} color="#0BA28D" />}
                      </div>
                      <div
                        style={{
                          fontSize: '0.8rem',
                          color: 'rgba(255, 255, 255, 0.7)',
                          lineHeight: 1.4
                        }}
                      >
                        Dedicates 100% of every spread to full-bleed photography with zero text boxes.
                      </div>
                    </button>
                  </div>

                  {includeText && (
                    <label
                      style={{
                        display: 'flex',
                        gap: '10px',
                        alignItems: 'flex-start',
                        marginTop: '0.85rem',
                        padding: '0.75rem 1rem',
                        background: 'rgba(255, 255, 255, 0.04)',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                        borderRadius: '12px',
                        cursor: isLoading ? 'default' : 'pointer'
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={usePhotoVision}
                        onChange={(e) => setUsePhotoVision(e.target.checked)}
                        disabled={isLoading}
                        style={{ marginTop: '3px', accentColor: '#0BA28D' }}
                      />
                      <span style={{ fontSize: '0.82rem', color: 'rgba(255, 255, 255, 0.9)' }}>
                        <strong>Let AI inspect a few photos to write captions</strong>
                        <br />
                        <small style={{ color: 'rgba(255, 255, 255, 0.55)', fontSize: '0.76rem' }}>
                          About 3 photos per chapter are sent to Google Gemini. Off by default.
                        </small>
                      </span>
                    </label>
                  )}

                  {/* Book Cover Title Card */}
                  <div
                    style={{
                      marginTop: '1rem',
                      paddingTop: '1rem',
                      borderTop: '1px solid rgba(255, 255, 255, 0.1)'
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: '0.65rem'
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.45rem',
                          fontWeight: 700,
                          fontSize: '0.88rem',
                          color: '#ffffff'
                        }}
                      >
                        <Type size={14} color="#4BB8C4" />
                        <span>Book Cover Title</span>
                      </div>
                      <button
                        type="button"
                        className="mx-cosmic-chip"
                        onClick={handleSuggestTitles}
                        disabled={isLoading || isSuggestingTitles}
                      >
                        {isSuggestingTitles ? (
                          <RefreshCw size={12} className="animate-spin" />
                        ) : (
                          <Sparkles size={12} color="#F2C94C" />
                        )}
                        <span>Suggest AI Titles</span>
                      </button>
                    </div>

                    {!isSuggestingTitles && suggestions && suggestions.titles && (
                      <div className="mx-cosmic-floating-chips" style={{ marginBottom: '0.65rem' }}>
                        {suggestions.titles.slice(0, 4).map((title, idx) => (
                          <button
                            key={idx}
                            type="button"
                            className={`mx-cosmic-chip ${selectedTitleIdx === idx ? 'active' : ''}`}
                            onClick={() => handlePickSuggestedCard(idx)}
                          >
                            {title}
                          </button>
                        ))}
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
                        value={customTitle}
                        onChange={(e) => {
                          setSelectedTitleIdx(null);
                          setCustomTitle(e.target.value);
                        }}
                        placeholder="Cover title (or leave blank for AI)..."
                        disabled={isLoading}
                        style={{
                          background: 'rgba(255, 255, 255, 0.06)',
                          border: '1px solid rgba(255, 255, 255, 0.15)',
                          borderRadius: '10px',
                          padding: '0.55rem 0.85rem',
                          color: '#ffffff',
                          fontSize: '0.86rem',
                          outline: 'none'
                        }}
                      />
                      <input
                        type="text"
                        value={customSubtitle}
                        onChange={(e) => setCustomSubtitle(e.target.value)}
                        placeholder="Optional subtitle (e.g. SUMMER 2026)..."
                        disabled={isLoading}
                        style={{
                          background: 'rgba(255, 255, 255, 0.06)',
                          border: '1px solid rgba(255, 255, 255, 0.15)',
                          borderRadius: '10px',
                          padding: '0.55rem 0.85rem',
                          color: '#ffffff',
                          fontSize: '0.86rem',
                          outline: 'none'
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div ref={threadEndRef} />
            </main>
          </div>

          {/* FLOATING NO-BOUNDARY BOTTOM TYPING SECTION & QUICK OPTIONS */}
          <div className="mx-cosmic-bottom-bar">
            <div className="mx-cosmic-bottom-inner">
              {/* Floating Quick Ideas / Followup Chips */}
              <div className="mx-cosmic-floating-chips">
                {FOLLOWUP_CHIPS.map((chip) => {
                  const active = selectedChips.includes(chip);
                  return (
                    <button
                      key={chip}
                      type="button"
                      className={`mx-cosmic-chip ${active ? 'active' : ''}`}
                      onClick={() => handleToggleFollowupChip(chip)}
                    >
                      {active && (
                        <Check
                          size={11}
                          strokeWidth={2.5}
                          style={{ marginRight: '4px', verticalAlign: '-1px' }}
                        />
                      )}
                      {chip}
                    </button>
                  );
                })}
              </div>

              {/* Visually Borderless / No Boundary Floating Typing Slot */}
              <form
                className="mx-cosmic-noboundary-input-wrap"
                onSubmit={handleSendMessage}
              >
                <button
                  type="button"
                  className="mx-cosmic-chip"
                  onClick={() => {
                    if (totalCount > 0) setIsPhotoModalOpen(true);
                    else triggerFilePicker();
                  }}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.45rem',
                    padding: '0.42rem 0.85rem'
                  }}
                  title="Upload or manage photos"
                >
                  <ImageIcon size={15} color="#4BB8C4" />
                  <span>Photos {totalCount > 0 ? `(${survivedCount})` : ''}</span>
                </button>

                <input
                  type="text"
                  className="mx-cosmic-noboundary-input"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Type your story, trip details, or wishes here... (No boundaries)"
                  disabled={isLoading}
                />

                <button
                  type="submit"
                  className="mx-cosmic-send-btn"
                  disabled={!chatInput.trim() || isLoading}
                  aria-label="Send message"
                >
                  <ArrowUp size={18} strokeWidth={2.5} />
                </button>

                <button
                  type="button"
                  className="mx-cosmic-launch-btn"
                  onClick={handleLaunchBookCreation}
                  disabled={isLoading || isWaitingForIngest || isDownsampling}
                >
                  {isWaitingForIngest ? (
                    <>
                      <RefreshCw size={16} strokeWidth={2} className="animate-spin" />
                      <span>Finishing upload...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} strokeWidth={2.2} />
                      <span>Start creating my book</span>
                    </>
                  )}
                </button>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Screen 1 Sticky Bottom Input Dock (Only when user has not started story yet) */}
      {!hasStartedStory && (
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
                placeholder="Or tell us in your own words..."
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
      )}

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
