import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
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
  Edit3,
  X
} from 'lucide-react';
import ParallaxHeroImages from './ui/ParallaxHeroImages';
import PixovoStoryIntro from './PixovoStoryIntro';
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

  // Step-by-step conversational questioning state
  const [selectedOccasion, setSelectedOccasion] = useState('');
  const [customOccasionText, setCustomOccasionText] = useState('');
  const [styleAnswered, setStyleAnswered] = useState(false);
  const [visionAnswered, setVisionAnswered] = useState(false);
  const [titleAnswered, setTitleAnswered] = useState(false);
  const [editingStep, setEditingStep] = useState(null);

  const defaultSuggestedTitles = useMemo(() => {
    if (suggestions?.titles && suggestions.titles.length > 0) {
      return suggestions.titles.slice(0, 4);
    }
    const occ = (selectedOccasion || userPrompt || '').toLowerCase();
    if (occ.includes('trip') || occ.includes('vacation') || occ.includes('travel')) {
      return ['Summer Road Notes', 'Coastal Wanderer', 'The Unplanned Journey', 'Chasing Horizons'];
    }
    if (occ.includes('gift') || occ.includes('heartfelt') || occ.includes('love')) {
      return ['For You, With Love', 'Moments We Treasure', 'A Gift of Memories', 'Thinking of You'];
    }
    if (occ.includes('milestone') || occ.includes('grad') || occ.includes('celebrat')) {
      return ['The Big Leap', 'Honoring the Journey', 'Milestones & Memories', 'Proud of You'];
    }
    if (occ.includes('family')) {
      return ['Together as Always', 'Everyday Magic', 'Our Family Chapter', 'Home & Heart'];
    }
    return ['Cherished Memories', 'A Collection of Moments', 'Captured Life', 'Our Story'];
  }, [suggestions, selectedOccasion, userPrompt]);

  const handlePickOccasion = (title) => {
    setSelectedOccasion(title);
    setEditingStep(null);
    setStyleAnswered(false);
    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: title };
    const aiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      text: generateContextualReply(title, messages.length)
    };
    const nextMsgs = [...messages, userMsg, aiMsg];
    setMessages(nextMsgs);
    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);
  };

  const handleCustomOccasionSubmit = (e) => {
    if (e) e.preventDefault();
    const trimmed = customOccasionText.trim();
    if (!trimmed) return;
    handlePickOccasion(trimmed);
    setCustomOccasionText('');
  };

  const handlePickStyle = (isCaptions) => {
    setIncludeText(isCaptions);
    setStyleAnswered(true);
    setEditingStep(null);
    if (!isCaptions) {
      setUsePhotoVision(false);
      setVisionAnswered(true);
    } else {
      setVisionAnswered(false);
    }
  };

  const handlePickVision = (useVision) => {
    setUsePhotoVision(useVision);
    setVisionAnswered(true);
    setEditingStep(null);
  };

  const handleConfirmTitle = () => {
    if (!customTitle.trim()) {
      setCustomTitle(defaultSuggestedTitles[0] || 'Cherished Memories');
    }
    if (!customSubtitle.trim()) {
      setCustomSubtitle('A COLLECTION OF MEMORIES');
    }
    setTitleAnswered(true);
    setEditingStep(null);
  };

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
    setSelectedOccasion(card.title);
    setStyleAnswered(false);
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
          SCREEN 1: CEREMONIAL INTRO & CLEAN HEARTFELT INTERFACE
          ================================================================= */}
      {!hasStartedStory && (
        <PixovoStoryIntro
          onSelectOccasion={handleStartWithOccasion}
          onStorySubmit={(text) => {
            const userMsg = { id: `u-${Date.now()}`, role: 'user', text };
            const aiMsg = {
              id: `a-${Date.now() + 1}`,
              role: 'ai',
              text: generateContextualReply(text, 0)
            };
            const nextMsgs = [userMsg, aiMsg];
            setMessages(nextMsgs);
            setUserPrompt(text);
          }}
          onTriggerFilePicker={triggerFilePicker}
          dragActive={dragActive}
          isLoading={isLoading}
        />
      )}

      {/* =================================================================
          SCREEN 2: CLEAN, WARM STORY CONVERSATION & PHOTO CURATION
          ================================================================= */}
      {hasStartedStory && (
        <div className="pixovo-chat-shell">
          {/* Top Stage Bar with Back navigation & Photo count */}
          <div className="pixovo-chat-top-bar">
            <button
              type="button"
              className="pixovo-chat-back-btn"
              onClick={() => {
                setMessages([]);
                setSelectedOccasion('');
                setStyleAnswered(false);
                setVisionAnswered(false);
                setTitleAnswered(false);
                setEditingStep(null);
              }}
              title="Return to Story Selector"
            >
              <ArrowLeft size={14} strokeWidth={2.4} />
              <span>Back to Story Selector</span>
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              {totalCount > 0 && (
                <button
                  type="button"
                  className="pixovo-chat-chip"
                  onClick={() => setIsPhotoModalOpen(true)}
                  title="View and manage selected photos"
                >
                  <ImageIcon size={13} color="#0BA28D" />
                  <span>{survivedCount} Photos</span>
                </button>
              )}
              <span className="pixovo-chat-stage-pill">
                <Heart size={13} strokeWidth={2.2} color="#0BA28D" />
                <span>pixovo · Story Mode</span>
              </span>
            </div>
          </div>

          {/* Centered Single-Column Conversational Question & Pick Stream */}
          <div className="pixovo-chat-stream">
            {/* Conversation History / Photo Greeting */}
            {messages.map((msg, idx) => {
              if (msg.role === 'user') {
                return (
                  <div key={msg.id || idx} className="pixovo-chat-user-row">
                    <div className="pixovo-chat-user-bubble">{msg.text}</div>
                  </div>
                );
              }
              return (
                <div key={msg.id || idx} className="pixovo-chat-ai-row">
                  <div className="pixovo-chat-ai-head">
                    <Sparkles size={13} strokeWidth={2.4} />
                    <span>Story Companion</span>
                  </div>
                  <p className="pixovo-chat-ai-text">{msg.text}</p>

                  {/* Compact Photo Strip attached to the welcoming turn */}
                  {idx === 1 && totalCount > 0 && (
                    <div style={{ marginTop: '0.4rem' }}>
                      <div className="pixovo-compact-photo-strip">
                        {inlineStripThumbs.slice(0, 6).map((item) => (
                          <div
                            key={item.photo_id}
                            className="pixovo-compact-photo-thumb"
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
                        {reconciledPhotos.length > 6 && (
                          <button
                            type="button"
                            className="pixovo-chat-chip"
                            onClick={() => setIsPhotoModalOpen(true)}
                            style={{ height: '44px', borderRadius: '10px' }}
                          >
                            +{reconciledPhotos.length - 6} more
                          </button>
                        )}
                      </div>

                      {/* Mini Scanning / Curation Progress if in progress */}
                      {(!isPhotoUploadComplete || isDownsampling) && (
                        <div style={{ marginTop: '0.6rem' }}>
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              fontSize: '0.76rem',
                              color: '#7E8D9E',
                              marginBottom: '0.3rem'
                            }}
                          >
                            <span>Scanning &amp; Curating Memories</span>
                            <span style={{ color: '#0BA28D', fontWeight: 700 }}>{uploadPct}%</span>
                          </div>
                          <div className="pixovo-chat-progress-track">
                            <div
                              className="pixovo-chat-progress-fill"
                              style={{ width: `${Math.max(8, uploadPct)}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Photo Dropzone Prompt if user arrived here without any photos yet */}
            {totalCount === 0 && !isDownsampling && (
              <div
                className="pixovo-step-card"
                onClick={triggerFilePicker}
                style={{
                  cursor: 'pointer',
                  border: '1.5px dashed rgba(11, 162, 141, 0.35)',
                  background: '#E8F6F4',
                  textAlign: 'center',
                  padding: '2rem'
                }}
              >
                <UploadCloud size={36} color="#0BA28D" style={{ margin: '0 auto 0.5rem' }} />
                <h4 style={{ margin: '0 0 0.25rem', fontSize: '1.05rem', fontWeight: 700, color: '#1F2937' }}>
                  Tap to add your photos to begin
                </h4>
                <p style={{ margin: 0, fontSize: '0.82rem', color: '#7E8D9E' }}>
                  Fast local curation • Automatically filters blurs and duplicates
                </p>
              </div>
            )}

            {/* =================================================================
                QUESTION 1: OCCASION / STORY THEME
                ================================================================= */}
            {selectedOccasion && editingStep !== 'occasion' ? (
              <div className="pixovo-step-card">
                <div className="pixovo-answered-pill">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                    <span>Story Theme: <strong>{selectedOccasion}</strong></span>
                  </span>
                  <button
                    type="button"
                    className="pixovo-change-btn"
                    onClick={() => setEditingStep('occasion')}
                  >
                    <Edit3 size={13} />
                    <span>Change</span>
                  </button>
                </div>
              </div>
            ) : (
              <div className="pixovo-step-card active-step">
                <div className="pixovo-step-header">
                  <span className="pixovo-step-badge">Question 1</span>
                  {selectedOccasion && (
                    <button
                      type="button"
                      className="pixovo-change-btn"
                      onClick={() => setEditingStep(null)}
                    >
                      Keep Current
                    </button>
                  )}
                </div>
                <h3 className="pixovo-step-title">What is this photo collection celebrating?</h3>
                <p className="pixovo-step-sub">Pick the occasion or mood that best fits your story:</p>

                <div className="pixovo-step-options">
                  {[
                    { id: 'trip', title: '🌴 My last trip', sub: 'Road trips, vacations & scenic adventures' },
                    { id: 'gift', title: '🎁 A heartfelt gift', sub: 'For someone special & cherished' },
                    { id: 'milestone', title: '🎓 A big milestone', sub: 'Graduations, weddings & accomplishments' },
                    { id: 'family', title: '👨‍👩‍👧 Family moments', sub: 'Everyday love, reunions & memories' }
                  ].map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`pixovo-pick-btn ${selectedOccasion === item.title ? 'selected' : ''}`}
                      onClick={() => handlePickOccasion(item.title)}
                    >
                      <div className="pixovo-pick-head">
                        <span>{item.title}</span>
                        {selectedOccasion === item.title && (
                          <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                        )}
                      </div>
                      <div className="pixovo-pick-sub">{item.sub}</div>
                    </button>
                  ))}
                </div>

                {/* Direct text option */}
                <form
                  onSubmit={handleCustomOccasionSubmit}
                  style={{ display: 'flex', gap: '0.5rem', marginTop: '0.2rem' }}
                >
                  <input
                    type="text"
                    className="pixovo-step-text-input"
                    placeholder="Or type your own story theme in text..."
                    value={customOccasionText}
                    onChange={(e) => setCustomOccasionText(e.target.value)}
                  />
                  <button
                    type="submit"
                    className="pixovo-step-action-btn"
                    disabled={!customOccasionText.trim()}
                  >
                    Set
                  </button>
                </form>
              </div>
            )}

            {/* =================================================================
                QUESTION 2: EDITORIAL PRESENTATION STYLE
                ================================================================= */}
            {selectedOccasion && (
              styleAnswered && editingStep !== 'style' ? (
                <div className="pixovo-step-card">
                  <div className="pixovo-answered-pill">
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                      <span>
                        Style: <strong>{includeText ? 'Storytelling Captions' : 'Clean Photo-Forward'}</strong>
                      </span>
                    </span>
                    <button
                      type="button"
                      className="pixovo-change-btn"
                      onClick={() => setEditingStep('style')}
                    >
                      <Edit3 size={13} />
                      <span>Change</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="pixovo-step-card active-step">
                  <div className="pixovo-step-header">
                    <span className="pixovo-step-badge">Question 2</span>
                    {styleAnswered && (
                      <button
                        type="button"
                        className="pixovo-change-btn"
                        onClick={() => setEditingStep(null)}
                      >
                        Keep Current
                      </button>
                    )}
                  </div>
                  <h3 className="pixovo-step-title">Which presentation style would you like for your pages?</h3>
                  <p className="pixovo-step-sub">Choose how your photos and story narrative should appear:</p>

                  <div className="pixovo-step-options">
                    <button
                      type="button"
                      className={`pixovo-pick-btn ${includeText && styleAnswered ? 'selected' : ''}`}
                      onClick={() => handlePickStyle(true)}
                    >
                      <div className="pixovo-pick-head">
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                          <BookOpen size={16} color="#0BA28D" />
                          Storytelling Captions
                        </span>
                        {includeText && styleAnswered && (
                          <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                        )}
                      </div>
                      <div className="pixovo-pick-sub">
                        Pairs AI-crafted narrative captions and chapter headers alongside your photos.
                      </div>
                    </button>

                    <button
                      type="button"
                      className={`pixovo-pick-btn ${!includeText && styleAnswered ? 'selected' : ''}`}
                      onClick={() => handlePickStyle(false)}
                    >
                      <div className="pixovo-pick-head">
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                          <ImageIcon size={16} color="#0BA28D" />
                          Clean Photo-Forward
                        </span>
                        {!includeText && styleAnswered && (
                          <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                        )}
                      </div>
                      <div className="pixovo-pick-sub">
                        Dedicates 100% of every spread to full-bleed photography with zero text boxes.
                      </div>
                    </button>
                  </div>
                </div>
              )
            )}

            {/* =================================================================
                QUESTION 3: SMART PHOTO VISION CAPTIONS (Only if includeText)
                ================================================================= */}
            {selectedOccasion && styleAnswered && includeText && (
              visionAnswered && editingStep !== 'vision' ? (
                <div className="pixovo-step-card">
                  <div className="pixovo-answered-pill">
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                      <span>
                        Captions: <strong>{usePhotoVision ? 'Smart Photo Vision (Gemini)' : 'Fast Chapter Themes'}</strong>
                      </span>
                    </span>
                    <button
                      type="button"
                      className="pixovo-change-btn"
                      onClick={() => setEditingStep('vision')}
                    >
                      <Edit3 size={13} />
                      <span>Change</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="pixovo-step-card active-step">
                  <div className="pixovo-step-header">
                    <span className="pixovo-step-badge">Question 3</span>
                    {visionAnswered && (
                      <button
                        type="button"
                        className="pixovo-change-btn"
                        onClick={() => setEditingStep(null)}
                      >
                        Keep Current
                      </button>
                    )}
                  </div>
                  <h3 className="pixovo-step-title">Would you like AI to inspect key photos for personal captions?</h3>
                  <p className="pixovo-step-sub">Select how deep AI should analyze your photos:</p>

                  <div className="pixovo-step-options">
                    <button
                      type="button"
                      className={`pixovo-pick-btn ${usePhotoVision && visionAnswered ? 'selected' : ''}`}
                      onClick={() => handlePickVision(true)}
                    >
                      <div className="pixovo-pick-head">
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                          <Sparkles size={16} color="#0BA28D" />
                          Yes, smart photo captions
                        </span>
                        {usePhotoVision && visionAnswered && (
                          <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                        )}
                      </div>
                      <div className="pixovo-pick-sub">
                        Sends ~3 key photos per chapter to Google Gemini for contextual narrative captions.
                      </div>
                    </button>

                    <button
                      type="button"
                      className={`pixovo-pick-btn ${!usePhotoVision && visionAnswered ? 'selected' : ''}`}
                      onClick={() => handlePickVision(false)}
                    >
                      <div className="pixovo-pick-head">
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                          <RefreshCw size={16} color="#0BA28D" />
                          Fast chapter themes
                        </span>
                        {!usePhotoVision && visionAnswered && (
                          <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                        )}
                      </div>
                      <div className="pixovo-pick-sub">
                        Generates chapter themes using your story notes without sending photos to Gemini.
                      </div>
                    </button>
                  </div>
                </div>
              )
            )}

            {/* =================================================================
                QUESTION 4: BOOK COVER TITLE & SUBTITLE
                ================================================================= */}
            {selectedOccasion && styleAnswered && (!includeText || visionAnswered) && (
              titleAnswered && editingStep !== 'title' ? (
                <div className="pixovo-step-card">
                  <div className="pixovo-answered-pill">
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Check size={16} color="#0BA28D" strokeWidth={2.5} />
                      <span>
                        Cover Title: <strong>"{customTitle || defaultSuggestedTitles[0]}"</strong>
                        {customSubtitle ? ` • ${customSubtitle}` : ''}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="pixovo-change-btn"
                      onClick={() => setEditingStep('title')}
                    >
                      <Edit3 size={13} />
                      <span>Change</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="pixovo-step-card active-step">
                  <div className="pixovo-step-header">
                    <span className="pixovo-step-badge">
                      Step {includeText ? '4' : '3'}
                    </span>
                    <button
                      type="button"
                      className="pixovo-change-btn"
                      onClick={handleSuggestTitles}
                      disabled={isSuggestingTitles}
                    >
                      {isSuggestingTitles ? (
                        <RefreshCw size={12} className="animate-spin" />
                      ) : (
                        <Sparkles size={12} />
                      )}
                      <span>Suggest Titles</span>
                    </button>
                  </div>
                  <h3 className="pixovo-step-title">What should we title the cover of your book?</h3>
                  <p className="pixovo-step-sub">Pick an AI-suggested title or enter your own custom text:</p>

                  {/* Clickable Title Chips to Pick */}
                  <div className="pixovo-chat-floating-chips" style={{ padding: 0 }}>
                    {defaultSuggestedTitles.map((title, idx) => (
                      <button
                        key={idx}
                        type="button"
                        className={`pixovo-chat-chip ${customTitle === title ? 'active' : ''}`}
                        onClick={() => {
                          setCustomTitle(title);
                          if (!customSubtitle) setCustomSubtitle('A COLLECTION OF MEMORIES');
                        }}
                      >
                        {title}
                      </button>
                    ))}
                  </div>

                  {/* Direct Text Inputs */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                    <input
                      type="text"
                      className="pixovo-step-text-input"
                      placeholder="Cover title (or pick a suggestion above)..."
                      value={customTitle}
                      onChange={(e) => setCustomTitle(e.target.value)}
                    />
                    <input
                      type="text"
                      className="pixovo-step-text-input"
                      placeholder="Optional subtitle (e.g. SUMMER 2026)..."
                      value={customSubtitle}
                      onChange={(e) => setCustomSubtitle(e.target.value)}
                    />
                  </div>

                  <button
                    type="button"
                    className="pixovo-step-action-btn"
                    onClick={handleConfirmTitle}
                  >
                    <span>Confirm Title &amp; Continue</span>
                    <ArrowRight size={15} />
                  </button>
                </div>
              )
            )}

            {/* =================================================================
                STEP 5: REVIEW & READY TO CREATE BOOK
                ================================================================= */}
            {selectedOccasion && styleAnswered && (!includeText || visionAnswered) && titleAnswered && (
              <div className="pixovo-recipe-card">
                <div className="pixovo-step-header">
                  <span className="pixovo-step-badge">
                    <Sparkles size={12} />
                    <span>Ready to Create</span>
                  </span>
                  <span style={{ fontSize: '0.8rem', color: '#0BA28D', fontWeight: 700 }}>
                    All Settings Configured
                  </span>
                </div>

                <h3 className="pixovo-step-title" style={{ fontSize: '1.25rem' }}>
                  Your custom book recipe is ready!
                </h3>

                <div className="pixovo-recipe-grid">
                  <div className="pixovo-recipe-item">
                    <span className="pixovo-recipe-label">Photos</span>
                    <span className="pixovo-recipe-val">
                      {survivedCount > 0 ? `${survivedCount} curated` : '0 selected'}
                    </span>
                  </div>

                  <div className="pixovo-recipe-item">
                    <span className="pixovo-recipe-label">Page Style</span>
                    <span className="pixovo-recipe-val">
                      {includeText ? 'Storytelling Captions' : 'Clean Photo-Forward'}
                    </span>
                  </div>

                  <div className="pixovo-recipe-item">
                    <span className="pixovo-recipe-label">AI Vision</span>
                    <span className="pixovo-recipe-val">
                      {includeText ? (usePhotoVision ? 'Gemini Smart Captions' : 'Fast Theme Layout') : 'Off (Photo-Forward)'}
                    </span>
                  </div>

                  <div className="pixovo-recipe-item">
                    <span className="pixovo-recipe-label">Cover Title</span>
                    <span className="pixovo-recipe-val" title={customTitle || 'A Collection of Memories'}>
                      "{customTitle || defaultSuggestedTitles[0] || 'A Collection of Memories'}"
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  className="pixovo-chat-launch-btn"
                  style={{
                    width: '100%',
                    justifyContent: 'center',
                    padding: '0.95rem 1.6rem',
                    fontSize: '1.02rem',
                    borderRadius: '16px'
                  }}
                  onClick={handleLaunchBookCreation}
                  disabled={isLoading || isDownsampling}
                >
                  <Sparkles size={18} strokeWidth={2.2} />
                  <span>Start Creating My Book</span>
                </button>
              </div>
            )}

            <div ref={threadEndRef} />
          </div>

          {/* FLOATING NO-BOUNDARY BOTTOM DOCK WITH AMBIENT GLOW */}
          <div className="pixovo-chat-bottom-bar">
            <div className="pixovo-chat-bottom-inner">
              <div style={{ position: 'relative', width: '100%' }}>
                <div className="pixovo-clean-dock-glow" />

                <form className="pixovo-chat-input-wrap" onSubmit={handleSendMessage}>
                  <button
                    type="button"
                    className="pixovo-chat-chip"
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
                    <ImageIcon size={15} color="#0BA28D" />
                    <span>Photos {totalCount > 0 ? `(${survivedCount})` : ''}</span>
                  </button>

                  <input
                    type="text"
                    className="pixovo-chat-input"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Add story notes, custom requests, or memories..."
                    disabled={isLoading}
                  />

                  <button
                    type="submit"
                    className="pixovo-chat-send-btn"
                    disabled={!chatInput.trim() || isLoading}
                    aria-label="Send message"
                  >
                    <ArrowUp size={18} strokeWidth={2.5} />
                  </button>

                  <button
                    type="button"
                    className="pixovo-chat-launch-btn"
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
                        <span>Create Book</span>
                      </>
                    )}
                  </button>
                </form>
              </div>
            </div>
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
