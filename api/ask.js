export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ ok: false, error: 'Method not allowed' });
  }

  try {
    const payload = typeof req.body === 'string' ? JSON.parse(req.body) : (req.body || {});
    const question = (payload.question || '').trim();
    const language = (payload.language || 'en').toLowerCase();

    if (!question) {
      return res.status(400).json({ ok: false, error: 'Question is required' });
    }

    const geminiKey = process.env.GEMINI_API_KEY || '';
    const groqKey = process.env.GROQ_API_KEY || '';

    // Match facts for context
    const matchFacts = `
Live Match Facts:
- Match: Royal Challengers vs Super Kings (Innings 2, Chase)
- Score: Royal Challengers 156/4 in 17.2 overs (Max 20 ov)
- Target: 182 | Need 26 runs from 16 balls | Required Run Rate: 9.75 | Current Run Rate: 9.00
- Batters: Virat Kohli 68* (42 balls, 5x4, 2x6) on strike, Hardik Pandya 19* (9 balls)
- Bowler: Mitchell Starc (3.2 overs, 1 wicket, 28 runs, economy 8.40)
- Current Partnership: 38 runs off 18 balls
- Win Probability: Royal Challengers 62%, Super Kings 38%
`;

    // 1. Try Gemini 2.5 Flash if API key is present
    if (geminiKey) {
      try {
        const langInstructions = {
          hi: 'Respond in natural conversational Hindi (हिंदी में उत्तर दें). Be friendly, accurate, and concise.',
          mr: 'Respond in natural Marathi (मराठीत उत्तर द्या). Be friendly and concise.',
          en: 'Respond in friendly, natural English. Be concise and accurate.'
        };
        const langPrompt = langInstructions[language] || langInstructions.en;

        const systemPrompt = `You are Cricket Dost (क्रिकेट दोस्त), an intelligent, context-aware AI Live Match Fan Companion for cricket fans.
${matchFacts}
${langPrompt}
Answer the user's question directly based on verified match facts or standard cricket rules. Never invent false stats. Keep answers within 2-4 sentences.`;

        const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${geminiKey}`;
        const resp = await fetch(geminiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contents: [
              { role: 'user', parts: [{ text: `${systemPrompt}\n\nFan Question: ${question}` }] }
            ],
            generationConfig: { maxOutputTokens: 250, temperature: 0.3 }
          })
        });

        if (resp.ok) {
          const data = await resp.json();
          const answerText = data?.candidates?.[0]?.content?.parts?.[0]?.text;
          if (answerText && answerText.trim()) {
            return res.status(200).json({
              ok: true,
              answer: answerText.trim(),
              model: 'gemini-2.5-flash',
              language: language
            });
          }
        }
      } catch (geminiErr) {
        console.error('Gemini error:', geminiErr);
      }
    }

    // 2. Try Groq Llama 3.3 if Groq key is present
    if (groqKey) {
      try {
        const groqResp = await fetch('https://api.groq.com/openai/v1/chat/completions', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${groqKey}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            model: 'llama-3.3-70b-versatile',
            messages: [
              {
                role: 'system',
                content: `You are Cricket Dost (क्रिकेट दोस्त), an AI cricket assistant. Answer in ${language === 'hi' ? 'Hindi' : (language === 'mr' ? 'Marathi' : 'English')}. ${matchFacts} Keep it brief and friendly.`
              },
              { role: 'user', content: question }
            ],
            max_tokens: 200,
            temperature: 0.3
          })
        });

        if (groqResp.ok) {
          const gdata = await groqResp.json();
          const ganswer = gdata?.choices?.[0]?.message?.content;
          if (ganswer && ganswer.trim()) {
            return res.status(200).json({
              ok: true,
              answer: ganswer.trim(),
              model: 'groq-llama-3.3',
              language: language
            });
          }
        }
      } catch (groqErr) {
        console.error('Groq error:', groqErr);
      }
    }

    // 3. Deterministic Context-Aware Fallback
    const qLower = question.toLowerCase();
    let reply = '';

    if (/^(hi|hello|hey|namaste|kem cho|pranam)/i.test(qLower)) {
      if (language === 'hi') {
        reply = 'नमस्ते! मैं क्रिकेट दोस्त हूँ — आपका लाइव मैच AI साथी। रॉयल चैलेंजर्स को जीत के लिए 16 गेंदों में 26 रनों की दरकार है। मैच स्थिति, स्कोर या नियमों के बारे में कुछ भी पूछें!';
      } else if (language === 'mr') {
        reply = 'नमस्कार! मी क्रिकेट दोस्त आहे — तुमचा लाईव्ह मॅच AI साथीदार! रॉयल चॅलेंजर्सला विजयासाठी 16 चेंडूंत 26 धावा हव्यात. धावसंख्या किंवा नियमांबद्दल मला विचारा!';
      } else {
        reply = 'Hello! I am Cricket Dost — your live match companion. Royal Challengers need 26 runs from 16 balls with Virat Kohli on 68*. Ask me anything about the match or rules!';
      }
    } else if (/score|target|rrr|situation|equation|runs/i.test(qLower)) {
      if (language === 'hi') {
        reply = 'रॉयल चैलेंजर्स 156/4 (17.2 ओवर)। जीत का लक्ष्य 182 रन है। अब 16 गेंदों में 26 रन चाहिए (RRR: 9.75)। विराट कोहली 68* रन बनाकर क्रीज पर डटे हुए हैं।';
      } else {
        reply = 'Royal Challengers are 156/4 in 17.2 overs chasing 182. They need 26 runs from 16 balls (RRR: 9.75). Virat Kohli is batting on 68*.';
      }
    } else if (/who is batting|batsman|batters|crease/i.test(qLower)) {
      if (language === 'hi') {
        reply = 'क्रीज पर विराट कोहली 68* (42 गेंद) और हार्दिक पांड्या 19* (9 गेंद) खेल रहे हैं। दोनों के बीच 18 गेंदों में 38 रनों की साझेदारी हो चुकी है।';
      } else {
        reply = 'At the crease: Virat Kohli 68* (42b) and Hardik Pandya 19* (9b), in a 38-run partnership off 18 balls.';
      }
    } else if (/who is bowling|bowler/i.test(qLower)) {
      if (language === 'hi') {
        reply = 'गेंदबाजी पर मिचेल स्टार्क हैं (3.2 ओवर, 28 रन, 1 विकेट, इकॉनमी 8.40)।';
      } else {
        reply = 'Mitchell Starc is bowling (3.2 overs, 1/28, economy 8.40).';
      }
    } else {
      if (language === 'hi') {
        reply = `रॉयल चैलेंजर्स 156/4 (17.2 ओवर) पर खेल रही है। लक्ष्य 182 है और 16 गेंदों में 26 रनों की आवश्यकता है। विराट कोहली 68* रन बनाकर स्ट्राइक पर हैं।`;
      } else {
        reply = `Royal Challengers are 156/4 in 17.2 overs chasing 182. They need 26 runs from 16 balls with Virat Kohli (68*) on strike.`;
      }
    }

    return res.status(200).json({
      ok: true,
      answer: reply,
      model: 'cricket-dost-engine',
      language: language
    });

  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message || 'Internal server error' });
  }
}

