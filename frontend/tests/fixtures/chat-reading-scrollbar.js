import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useChatReading } from '../../src/useChatReading';
import { ChatReadingPositions } from '../../src/chat-reading-position';
import '../../src/styles.css';

const positions = new ChatReadingPositions();
const messages = Array.from({length:40}, (_, index) => ({id:`message-${index}`, text:`正文 ${index}`}));
function ReadingFixture() {
  const [session, setSession] = useState({id:'scrollbar-test', messages});
  const [width, setWidth] = useState(600);
  const reading = useChatReading(session, positions, true, true, null);
  window.readingFixture = {
    append:() => setSession(previous => ({...previous, messages:[...previous.messages,
      {id:`message-${previous.messages.length}`, text:'新的流式正文'}]})),
    resize:() => setWidth(previous => previous === 600 ? 500 : 600),
    snapshot:() => {
      const element = reading.timeline.current;
      return {scrollTop:element.scrollTop, height:element.clientHeight, total:element.scrollHeight,
        following:reading.following, hasNewContent:reading.hasNewContent};
    },
  };
  return React.createElement('div', {className:'conversation-timeline', style:{height:400, width, flex:'none', margin:20}},
    React.createElement('div', {className:'timeline', ref:reading.timeline, tabIndex:0},
      React.createElement('div', {className:'message-container'}, session.messages.map(message =>
        React.createElement('div', {key:message.id, 'data-reading-anchor':message.id, style:{height:100}}, message.text)))),
    !reading.following && React.createElement('div', {className:'reading-controls'},
      React.createElement('button', {onClick:reading.scrollToLatest}, '回到底部')));
}
createRoot(document.getElementById('root')).render(React.createElement(ReadingFixture));
