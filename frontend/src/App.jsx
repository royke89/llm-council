import { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import ReviewModal from './components/ReviewModal';
import { api } from './api';
import './App.css';

const makeAssistantPlaceholder = () => ({
  role: 'assistant',
  stage1: null,
  stage2: null,
  stage3: null,
  metadata: null,
  loading: { stage1: false, stage2: false, stage3: false },
});

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showReview, setShowReview] = useState(false);
  // When we create+select a conversation with optimistic messages, skip the
  // automatic reload that would otherwise wipe them.
  const suppressLoadRef = useRef(null);

  useEffect(() => {
    loadConversations();
  }, []);

  useEffect(() => {
    if (currentConversationId) {
      if (suppressLoadRef.current === currentConversationId) {
        suppressLoadRef.current = null;
        return;
      }
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  // Shared handler for council stage-streaming events (chat + review).
  const handleStreamEvent = (eventType, event) => {
    switch (eventType) {
      case 'stage1_start':
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          messages[messages.length - 1].loading.stage1 = true;
          return { ...prev, messages };
        });
        break;
      case 'stage1_complete':
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          const last = messages[messages.length - 1];
          last.stage1 = event.data;
          last.loading.stage1 = false;
          return { ...prev, messages };
        });
        break;
      case 'stage2_start':
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          messages[messages.length - 1].loading.stage2 = true;
          return { ...prev, messages };
        });
        break;
      case 'stage2_complete':
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          const last = messages[messages.length - 1];
          last.stage2 = event.data;
          last.metadata = event.metadata;
          last.loading.stage2 = false;
          return { ...prev, messages };
        });
        break;
      case 'stage3_start':
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          messages[messages.length - 1].loading.stage3 = true;
          return { ...prev, messages };
        });
        break;
      case 'stage3_complete':
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          const last = messages[messages.length - 1];
          last.stage3 = event.data;
          last.loading.stage3 = false;
          return { ...prev, messages };
        });
        break;
      case 'title_complete':
        loadConversations();
        break;
      case 'complete':
        loadConversations();
        setIsLoading(false);
        break;
      case 'error':
        console.error('Stream error:', event.message);
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          const last = messages[messages.length - 1];
          if (last && last.role === 'assistant') {
            last.loading = { stage1: false, stage2: false, stage3: false };
            last.stage3 = { model: 'error', response: 'Error: ' + event.message };
          }
          return { ...prev, messages };
        });
        setIsLoading(false);
        break;
      default:
        console.log('Unknown event type:', eventType);
    }
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;
    setIsLoading(true);
    try {
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          { role: 'user', content },
          makeAssistantPlaceholder(),
        ],
      }));
      await api.sendMessageStream(currentConversationId, content, handleStreamEvent);
    } catch (error) {
      console.error('Failed to send message:', error);
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  const handleRunReview = async (params) => {
    setShowReview(false);
    setIsLoading(true);
    try {
      const newConv = await api.createConversation();
      setConversations((prev) => [
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...prev,
      ]);
      const userContent =
        `📁 Project review: ${params.path}\n\n` +
        `**Request:** ${params.question || 'General code review'}`;
      suppressLoadRef.current = newConv.id;
      setCurrentConversationId(newConv.id);
      setCurrentConversation({
        ...newConv,
        messages: [{ role: 'user', content: userContent }, makeAssistantPlaceholder()],
      });
      await api.reviewStream(newConv.id, params, handleStreamEvent);
      await loadConversation(newConv.id);
    } catch (error) {
      console.error('Failed to run review:', error);
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        onReviewProject={() => setShowReview(true)}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
      />
      {showReview && (
        <ReviewModal
          onRun={handleRunReview}
          onClose={() => setShowReview(false)}
          isRunning={isLoading}
        />
      )}
    </div>
  );
}

export default App;
