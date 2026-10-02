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
  ChevronDown,
  X,
  SkipForward
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

// Custom typewriter effect for AI message text with natural streaming and fading options
function PixovoTypewriterMessage({
  text,
  readyContent = null,
  speed = 18,
  isLatest = false,
  isCompleted = false,
  onComplete,
  children
}) {
  const [displayedText, setDisplayedText] = useState(isCompleted || !isLatest ? text : '');
  const [done, setDone] = useState(isCompleted || !isLatest);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (isCompleted || !isLatest) {
      setDisplayedText(text);
      setDone(true);
      return;
    }

    setDisplayedText('');
    setDone(false);
    let index = 0;
    const step = 2; // Stream 2 characters per tick for smooth natural LLM pace

    const timer = setInterval(() => {
      index += step;
      if (index >= text.length) {
        setDisplayedText(text);
        setDone(true);
        clearInterval(timer);
        if (onCompleteRef.current) {
          onCompleteRef.current();
        }
      } else {
        setDisplayedText(text.slice(0, index));
      }
    }, speed);

    return () => clearInterval(timer);
  }, [text, isLatest, isCompleted, speed]);

  return (
    <>
      {done && readyContent ? (
        readyContent
      ) : (
        <p className="pixovo-chat-ai-text">
          {displayedText}
          {!done && <span className="pixovo-typing-cursor" aria-hidden="true" />}
        </p>
      )}

      {/* Choice Pills & Action Options fade in smoothly once typing finishes */}
      {done && children && (
        <div className="pixovo-options-fade-in">
          {children}
        </div>
      )}
    </>
  );
}

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
  const [messages, setMessages] = useState([]);
  const [completedTypingIds, setCompletedTypingIds] = useState(() => new Set());

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

  // Local worker downsampling states
  const [isDownsampling, setIsDownsampling] = useState(false);
  const [downsampleStats, setDownsampleStats] = useState({ completed: 0, total: 0 });
  const [dragActive, setDragActive] = useState(false);
  const [isPhotoModalOpen, setIsPhotoModalOpen] = useState(false);

  // Calculate inline upload numbers for Story Mode
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

  const getStylePromptText = (occ) => {
    const lower = (occ || '').toLowerCase();
    if (lower.includes('trip') || lower.includes('travel') || lower.includes('vacation')) {
      return 'A travel story! Which presentation style would you prefer for your pages?';
    }
    if (
      lower.includes('everyday') ||
      lower.includes('gallery') ||
      lower.includes('casual') ||
      lower.includes('random') ||
      lower.includes('photos') ||
      lower.includes("don't know") ||
      lower.includes('dont know') ||
      lower.includes('not sure')
    ) {
      return 'Everyday memories make wonderful keepsakes! Which presentation style would you prefer for your pages?';
    }
    if (lower.includes('family')) {
      return 'Family moments are timeless. Which presentation style would you prefer for your pages?';
    }
    if (lower.includes('gift') || lower.includes('heartfelt')) {
      return 'A special keepsake gift! Which presentation style would you prefer for your pages?';
    }
    if (lower.includes('milestone') || lower.includes('grad') || lower.includes('wedding')) {
      return 'A great celebration! Which presentation style would you prefer for your pages?';
    }
    return 'Which presentation style would you prefer for your pages?';
  };

  const handlePickOccasion = (title) => {
    setSelectedOccasion(title);
    setStyleAnswered(false);
    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: title };
    const nextAiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      step: 'style',
      text: getStylePromptText(title)
    };
    const nextMsgs = [...messages, userMsg, nextAiMsg];
    setMessages(nextMsgs);
    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);
    setTimeout(() => scrollToBottom('smooth'), 60);
  };

  const handlePickStyle = (isCaptions) => {
    setIncludeText(isCaptions);
    setStyleAnswered(true);
    const choiceText = isCaptions ? 'Storytelling Captions' : 'Clean Photo-Forward';
    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: choiceText };

    let nextAiMsg;
    if (isCaptions) {
      setUsePhotoVision(false);
      setVisionAnswered(false);
      nextAiMsg = {
        id: `a-${Date.now() + 1}`,
        role: 'ai',
        step: 'vision',
        text: 'Storytelling captions will add rich narrative context. Would you like our AI to inspect key photos with Gemini for personal captions?'
      };
    } else {
      setUsePhotoVision(false);
      setVisionAnswered(true);
      nextAiMsg = {
        id: `a-${Date.now() + 1}`,
        role: 'ai',
        step: 'title',
        text: 'Clean photo-forward it is — pure visual focus. What should we title the cover of your book? Pick an idea below, type your own, or skip to use our default title:'
      };
    }
    const nextMsgs = [...messages, userMsg, nextAiMsg];
    setMessages(nextMsgs);
    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);
    setTimeout(() => scrollToBottom('smooth'), 60);
  };

  const handlePickVision = (useVision) => {
    setUsePhotoVision(useVision);
    setVisionAnswered(true);
    const choiceText = useVision ? 'Yes, smart photo captions' : 'Fast chapter themes';
    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: choiceText };
    const nextAiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      step: 'title',
      text: 'What should we title the cover of your book? Pick an idea below, type your own, or skip to use our default title:'
    };
    const nextMsgs = [...messages, userMsg, nextAiMsg];
    setMessages(nextMsgs);
    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);
    setTimeout(() => scrollToBottom('smooth'), 60);
  };

  const handleConfirmTitle = (chosenTitle, isSkipped = false) => {
    const titleToUse = isSkipped
      ? (defaultSuggestedTitles[0] || 'Cherished Memories')
      : (chosenTitle || customTitle.trim() || defaultSuggestedTitles[0] || 'Cherished Memories');

    setCustomTitle(titleToUse);
    if (!customSubtitle.trim()) {
      setCustomSubtitle('A COLLECTION OF MEMORIES');
    }
    setTitleAnswered(true);

    const userText = isSkipped
      ? 'Skip'
      : (chosenTitle ? chosenTitle : `Cover Title: "${titleToUse}"`);
    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: userText };

    const styleDesc = includeText
      ? (usePhotoVision ? 'Storytelling Captions (AI Vision)' : 'Storytelling Captions')
      : 'Clean Photo-Forward';
    const pCount = survivedCount || totalCount;

    const readyAiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      step: 'ready',
      text: `Your book is ready! We'll create your edition with ${pCount} curated photos, ${styleDesc}, and titled "${titleToUse}".`
    };

    const nextMsgs = [...messages, userMsg, readyAiMsg];
    setMessages(nextMsgs);
    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);
    setTimeout(() => scrollToBottom('smooth'), 60);
  };

  const handleRestartChoices = () => {
    setStyleAnswered(false);
    setVisionAnswered(false);
    setTitleAnswered(false);
    const retryAiMsg = {
      id: `a-${Date.now()}`,
      role: 'ai',
      step: 'style',
      text: 'Which presentation style would you prefer for your pages?'
    };
    setMessages(prev => [...prev, retryAiMsg]);
    setTimeout(() => scrollToBottom('smooth'), 60);
  };

  const fileInputRef = useRef(null);
  const threadEndRef = useRef(null);
  const downsamplerRef = useRef(null);
  const [showScrollBottom, setShowScrollBottom] = useState(false);

  const scrollToBottom = useCallback((behavior = 'smooth') => {
    if (threadEndRef.current) {
      threadEndRef.current.scrollIntoView({ behavior, block: 'end' });
    } else {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior });
    }
  }, []);

  // Listen to window scroll to show/hide scroll to bottom button
  useEffect(() => {
    const handleScroll = () => {
      const scrollY = window.scrollY || document.documentElement.scrollTop;
      const windowHeight = window.innerHeight;
      const docHeight = document.documentElement.scrollHeight;
      const distanceFromBottom = docHeight - (scrollY + windowHeight);
      setShowScrollBottom(distanceFromBottom > 150);
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

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

  // Determine if user has entered the active conversational thread (only after intro + photo animation complete)
  const [isIntroDone, setIsIntroDone] = useState(false);
  const hasStartedStory = isIntroDone;

  // By default on story open, messages update, or option pick, scroll smoothly to bottom
  useEffect(() => {
    if (hasStartedStory) {
      const timer = setTimeout(() => {
        scrollToBottom('smooth');
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [
    hasStartedStory,
    messages,
    selectedOccasion,
    styleAnswered,
    visionAnswered,
    titleAnswered,
    editingStep,
    scrollToBottom
  ]);

  // Initialize Question 1 when story mode begins
  useEffect(() => {
    if (hasStartedStory && messages.length === 0 && !selectedOccasion && totalCount > 0) {
      setMessages([
        {
          id: 'msg-q-occasion',
          role: 'ai',
          step: 'occasion',
          text: 'What is this photo collection celebrating? Choose an occasion below, or type your own in the chat:'
        }
      ]);
    }
  }, [hasStartedStory, messages.length, selectedOccasion, totalCount]);

  // Build combined narrative prompt from user messages + selected chips
  const computeEffectivePrompt = (msgs = messages, chips = selectedChips) => {
    const userTexts = msgs.filter((m) => m.role === 'user').map((m) => m.text);
    const base = userTexts.join(' — ');
    const chipStr = chips.length > 0 ? ` (${chips.join(', ')})` : '';
    return (base + chipStr).trim() || userPrompt || 'Cherished Memories';
  };

  const handleSendMessage = (e) => {
    if (e) e.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed) return;

    if (!selectedOccasion) {
      setSelectedOccasion(trimmed);
      setStyleAnswered(false);
      const userMsg = { id: `u-${Date.now()}`, role: 'user', text: trimmed };
      const qStyleMsg = {
        id: `a-${Date.now() + 1}`,
        role: 'ai',
        step: 'style',
        text: getStylePromptText(trimmed)
      };
      const nextMsgs = [...messages, userMsg, qStyleMsg];
      setMessages(nextMsgs);
      setChatInput('');
      const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
      setUserPrompt(nextPrompt);
      setTimeout(() => scrollToBottom('smooth'), 60);
      return;
    }

    if (!styleAnswered) {
      const lower = trimmed.toLowerCase();
      if (lower.includes('caption') || lower.includes('story') || lower.includes('text')) {
        setChatInput('');
        handlePickStyle(true);
        return;
      }
      if (lower.includes('photo') || lower.includes('clean') || lower.includes('no text')) {
        setChatInput('');
        handlePickStyle(false);
        return;
      }
    }

    if (styleAnswered && includeText && !visionAnswered) {
      const lower = trimmed.toLowerCase();
      if (lower.includes('yes') || lower.includes('smart') || lower.includes('vision') || lower.includes('gemini')) {
        setChatInput('');
        handlePickVision(true);
        return;
      }
      if (lower.includes('no') || lower.includes('fast') || lower.includes('theme') || lower.includes('skip')) {
        setChatInput('');
        handlePickVision(false);
        return;
      }
    }

    if (styleAnswered && (!includeText || visionAnswered) && !titleAnswered) {
      setChatInput('');
      if (trimmed.toLowerCase() === 'skip') {
        handleConfirmTitle(null, true);
      } else {
        handleConfirmTitle(trimmed, false);
      }
      return;
    }

    const userMsg = { id: `u-${Date.now()}`, role: 'user', text: trimmed };
    const aiMsg = {
      id: `a-${Date.now() + 1}`,
      role: 'ai',
      text: "Got it — I've noted that preference for your book design. Tap 'Create My Story Book' whenever you're ready!"
    };
    const nextMsgs = [...messages, userMsg, aiMsg];
    setMessages(nextMsgs);
    setChatInput('');

    const nextPrompt = computeEffectivePrompt(nextMsgs, selectedChips);
    setUserPrompt(nextPrompt);

    setTimeout(() => {
      scrollToBottom('smooth');
    }, 60);
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

  return (
    <div
      className={hasStartedStory ? "pixovo-story-root mx-story-shell" : "pixovo-story-root mx-hero-shell-wrap"}
      style={{
        width: '100%',
        maxWidth: '100%',
        margin: 0,
        padding: 0,
        background: 'transparent',
        border: 'none',
        borderRadius: 0,
        boxShadow: 'none',
        overflow: 'visible',
        transform: 'none',
        animation: 'none'
      }}
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
          onPhotosSelected={handleFilesSelected}
          onReadyForChat={() => setIsIntroDone(true)}
          isLoading={isLoading || isDownsampling}
        />
      )}

      {/* =================================================================
          SCREEN 2: CLEAN, WARM STORY CONVERSATION & PHOTO CURATION
          ================================================================= */}
      {hasStartedStory && (
        <div
          className="pixovo-chat-shell"
          style={{
            backgroundColor: '#F7F4F0',
            background: '#F7F4F0',
            border: 'none',
            borderRadius: 0,
            boxShadow: 'none',
            outline: 'none',
            width: '100%',
            minHeight: '100vh',
            transform: 'none'
          }}
        >
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
                setUserPrompt('');
                setCompletedTypingIds(new Set());
                setIsIntroDone(false);
              }}
              title="Return to Story Selector"
            >
              <ArrowLeft size={14} strokeWidth={2.4} />
              <span>Back to Story Selector</span>
            </button>
            {totalCount > 0 && !isPhotoModalOpen && (
              <button
                type="button"
                className="pixovo-left-media-trigger-btn"
                onClick={() => setIsPhotoModalOpen(true)}
                title="Open Media Tab on left"
              >
                <ImageIcon size={14} color="#0BA28D" />
                <span>Media ({survivedCount || totalCount})</span>
              </button>
            )}
          </div>

          {/* Centered Single-Column Conversational Question & Pick Stream */}
          <div className="pixovo-chat-stream">
            {/* Conversation History & In-Stream Choice Actions */}
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
                  <div className="pixovo-chat-ai-avatar">
                    <Sparkles size={15} strokeWidth={2.2} />
                  </div>
                  <div className="pixovo-chat-ai-content">
                    <PixovoTypewriterMessage
                      text={msg.text}
                      speed={16}
                      isLatest={idx === messages.length - 1}
                      isCompleted={completedTypingIds.has(msg.id || idx)}
                      onComplete={() => {
                        setCompletedTypingIds((prev) => new Set(prev).add(msg.id || idx));
                        setTimeout(() => scrollToBottom('smooth'), 50);
                      }}
                      readyContent={
                        msg.step === 'ready' ? (
                          <p className="pixovo-chat-ai-text">
                            Your book is ready! We'll create your edition with <strong>{survivedCount || totalCount} curated photos</strong>, <strong>{includeText ? (usePhotoVision ? 'Storytelling Captions (AI Vision)' : 'Storytelling Captions') : 'Clean Photo-Forward'}</strong>, and titled <strong>"{customTitle || defaultSuggestedTitles[0] || 'Cherished Memories'}"</strong>.
                          </p>
                        ) : null
                      }
                    >
                      {/* Step 1: Occasion Pills (only shown if occasion not yet answered) */}
                      {msg.step === 'occasion' && !selectedOccasion && (
                        <div className="pixovo-pill-options" style={{ marginTop: '0.65rem' }}>
                          {[
                            { id: 'trip', title: '🌴 My last trip' },
                            { id: 'gift', title: '🎁 A heartfelt gift' },
                            { id: 'milestone', title: '🎓 A big milestone' },
                            { id: 'family', title: '👨‍👩‍👧 Family moments' },
                            { id: 'everyday', title: '📷 Everyday memories' }
                          ].map((item) => (
                            <button
                              key={item.id}
                              type="button"
                              className="pixovo-choice-pill"
                              onClick={() => handlePickOccasion(item.title)}
                            >
                              {item.title}
                            </button>
                          ))}
                        </div>
                      )}

                      {/* Step 2: Presentation Style Pills (only on active question) */}
                      {msg.step === 'style' && !styleAnswered && idx === messages.length - 1 && (
                        <div className="pixovo-pill-options">
                          <button
                            type="button"
                            className="pixovo-choice-pill"
                            onClick={() => handlePickStyle(true)}
                          >
                            <BookOpen size={14} color="#0BA28D" />
                            <span>Storytelling Captions</span>
                          </button>
                          <button
                            type="button"
                            className="pixovo-choice-pill"
                            onClick={() => handlePickStyle(false)}
                          >
                            <ImageIcon size={14} color="#0BA28D" />
                            <span>Clean Photo-Forward</span>
                          </button>
                        </div>
                      )}

                      {/* Step 3: Smart Captions Pills (only on active question) */}
                      {msg.step === 'vision' && !visionAnswered && idx === messages.length - 1 && (
                        <div className="pixovo-pill-options">
                          <button
                            type="button"
                            className="pixovo-choice-pill"
                            onClick={() => handlePickVision(true)}
                          >
                            <Sparkles size={14} color="#0BA28D" />
                            <span>Yes, smart photo captions</span>
                          </button>
                          <button
                            type="button"
                            className="pixovo-choice-pill"
                            onClick={() => handlePickVision(false)}
                          >
                            <RefreshCw size={14} color="#0BA28D" />
                            <span>Fast chapter themes</span>
                          </button>
                        </div>
                      )}

                      {/* Step 4: Cover Title Pills + SKIP Option (only on active question) */}
                      {msg.step === 'title' && !titleAnswered && idx === messages.length - 1 && (
                        <div className="pixovo-pill-options">
                          {defaultSuggestedTitles.map((title, tIdx) => (
                            <button
                              key={tIdx}
                              type="button"
                              className="pixovo-choice-pill"
                              onClick={() => handleConfirmTitle(title, false)}
                            >
                              {title}
                            </button>
                          ))}
                          <button
                            type="button"
                            className="pixovo-choice-pill pixovo-skip-pill"
                            onClick={() => handleConfirmTitle(null, true)}
                            title="Skip choosing a custom title"
                          >
                            <SkipForward size={14} color="#0BA28D" />
                            <span>Skip</span>
                          </button>
                        </div>
                      )}

                      {/* Step 5: Ready to create book (only on ready step or final active state) */}
                      {(msg.step === 'ready' || (titleAnswered && idx === messages.length - 1)) && (
                        <div className="pixovo-pill-options" style={{ marginTop: '0.4rem' }}>
                          <button
                            type="button"
                            className="pixovo-chat-launch-btn"
                            onClick={handleLaunchBookCreation}
                            disabled={isLoading || isDownsampling}
                          >
                            <Sparkles size={16} strokeWidth={2.2} />
                            <span>Create My Story Book</span>
                          </button>
                          <button
                            type="button"
                            className="pixovo-choice-pill"
                            onClick={handleRestartChoices}
                            title="Adjust settings"
                          >
                            <Edit3 size={13} />
                            <span>Change choices</span>
                          </button>
                        </div>
                      )}
                    </PixovoTypewriterMessage>
                  </div>
                </div>
              );
            })}

            {/* If 0 photos and user entered chat, prompt them gently without any big dashed box */}
            {totalCount === 0 && !isDownsampling && (
              <div className="pixovo-chat-ai-row">
                <div className="pixovo-chat-ai-avatar">
                  <Sparkles size={15} strokeWidth={2.2} />
                </div>
                <div className="pixovo-chat-ai-content">
                  <p className="pixovo-chat-ai-text">
                    Welcome to Story Mode! To get started on your photobook, tap the photo icon in the bar below or drop your images anywhere on this page.
                  </p>
                </div>
              </div>
            )}
            <div ref={threadEndRef} />
          </div>

          {/* FLOATING SCROLL TO BOTTOM BUTTON (ChatGPT / Gemini style) */}
          {showScrollBottom && (
            <button
              type="button"
              className="pixovo-scroll-bottom-btn"
              onClick={() => scrollToBottom('smooth')}
              aria-label="Scroll to bottom"
              title="Scroll to bottom"
            >
              <ChevronDown size={18} strokeWidth={2.5} />
            </button>
          )}

          {/* FLOATING NO-BOUNDARY BOTTOM DOCK WITH AMBIENT GLOW */}
          <div className="pixovo-chat-bottom-bar">
            <div className="pixovo-chat-bottom-inner">
              <div style={{ position: 'relative', width: '100%' }}>
                <div className="pixovo-clean-dock-glow" />

                <form className="pixovo-chat-input-wrap" onSubmit={handleSendMessage}>
                  {/* Media button strictly on left side */}
                  <button
                    type="button"
                    className={`pixovo-chat-media-btn ${isPhotoModalOpen ? 'active' : ''}`}
                    onClick={() => {
                      if (totalCount > 0) setIsPhotoModalOpen((prev) => !prev);
                      else triggerFilePicker();
                    }}
                    title={totalCount > 0 ? (isPhotoModalOpen ? "Close Media Tab" : `Open Media Tab (${survivedCount || totalCount} photos)`) : "Upload photos"}
                    aria-label="Toggle Media Tab"
                  >
                    <ImageIcon size={17} strokeWidth={2.2} color="#0BA28D" />
                  </button>

                  <input
                    type="text"
                    className="pixovo-chat-input"
                    value={chatInput}
                    onFocus={() => scrollToBottom('smooth')}
                    onChange={(e) => {
                      setChatInput(e.target.value);
                      scrollToBottom('smooth');
                    }}
                    placeholder="Ask a question, add details, or customize your book..."
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
          LEFT EMPTY SPACE MEDIA TAB (Opens on left side empty space only)
          ================================================================= */}
      {isPhotoModalOpen && (
        <>
          {/* Mobile-only backdrop (hidden on desktop so left empty space is unobstructed) */}
          <div
            className="pixovo-media-mobile-backdrop"
            onClick={() => setIsPhotoModalOpen(false)}
          />

          <aside className="pixovo-media-left-tab" aria-label="Media tab">
            <div className="pixovo-media-left-tab-header">
              <div className="pixovo-media-left-tab-title">
                <ImageIcon size={17} color="#0BA28D" />
                <span>Media</span>
                <span className="pixovo-media-tab-badge">
                  {survivedCount || totalCount}
                </span>
              </div>

              <div className="pixovo-media-left-tab-actions">
                <button
                  type="button"
                  className="pixovo-media-left-tab-add-btn"
                  onClick={triggerFilePicker}
                  title="Add or replace photos"
                >
                  <Plus size={14} />
                  <span>Add</span>
                </button>
                <button
                  type="button"
                  className="pixovo-media-left-tab-close-btn"
                  onClick={() => setIsPhotoModalOpen(false)}
                  aria-label="Close media tab"
                  title="Close media tab"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="pixovo-media-left-tab-sub">
              <span>{isPhotoUploadComplete ? `${survivedCount} curated photos` : `Curating (${completedCount}/${totalCount})...`}</span>
              {(!isPhotoUploadComplete || isDownsampling) && (
                <span style={{ color: '#0BA28D', fontWeight: 700 }}>{uploadPct}%</span>
              )}
            </div>

            <div className="pixovo-media-left-tab-body">
              <div className="pixovo-media-left-tab-grid">
                {reconciledPhotos.map((item) => (
                  <div
                    key={item.photo_id}
                    className={`pixovo-media-left-tab-tile curation-tile-${item.status}`}
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
                      style={{ width: '100%', height: '100%', borderRadius: '8px' }}
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
          </aside>
        </>
      )}
    </div>
  );
}
