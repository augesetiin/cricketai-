# 🏏 CricketStream • AI Live Match Fan Companion

> **Challenge Problem Statement:**  
> *"Submit your AI-built artifact that solves a real problem fans face during a live sports match by analyzing every POV of fans."*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org/downloads)
[![AI Powered](https://img.shields.io/badge/AI-Google%20Gemini%202.5%20Flash-orange?logo=google&logoColor=white)](https://deepmind.google/)
[![Fast Inference](https://img.shields.io/badge/Fallback-Groq%20Llama%203.3-red)](https://groq.com/)
[![Tests](https://img.shields.io/badge/Tests-340%2B%20Passing%20(100%25)-brightgreen)](tests/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

---

## 🌟 Executive Summary: Solving the Live Sports Fan Dilemma

Live cricket is unpredictable, jargon-heavy, and consumed across wildly different real-world situations. Traditional sports apps force a **one-size-fits-all** layout onto every viewer: cluttered with complex statistics, full of confusing abbreviations (`RRR`, `SR`, `DLS`, `Doosra`), bandwidth-heavy, and demanding constant visual focus.

**CricketStream Fan Companion** fundamentally redesigns the fan experience. Using real-time match state reconciliation, computer-verified event detection, and generative AI, it adapts its interface, commentary personality, and data density to match how each fan is actually following the game.

Fans can seamlessly switch between **6 Adaptive Fan Perspectives** with zero page reloads.

---

## 🎭 The 6 Adaptive Fan Perspectives

```
┌────────────────────────────────────────────────────────────────────────┐
│                      HOW ARE YOU WATCHING TODAY?                       │
├────────────────────┬────────────────────┬──────────────────────────────┤
│ ⚡ THE LATE JOINER │ 🔰 CASUAL/BEGINNER │ 🎯 DEEP TACTICAL             │
│ 30-sec recap, key  │ Plain-language, no │ Live Win Probability, death- │
│ wickets & turning  │ jargon, Top 10 IPL │ over matchups & batter vs    │
│ point highlights   │ language explainer │ bowler historical data       │
├────────────────────┼────────────────────┼──────────────────────────────┤
│ 🚗 BUSY / DRIVING  │ 🏟️ IN-STADIUM      │ 🌟 ALL-ROUNDER               │
│ Eyes-off live radio│ Sunlight-readable, │ Complete match hub: smart    │
│ presenter audio &  │ sub-second sync,   │ timeline, Cricket Dost AI &  │
│ zero distraction   │ DLS par & DRS sync │ spoiler delay protection     │
└────────────────────┴────────────────────┴──────────────────────────────┘
```

### 1. ⚡ The Late Joiner
* **Problem:** Fans tune in during over 16 of a run chase without knowing how the game reached its current state.
* **Solution:** Instant **"Catch Me Up"** card delivering a concise 30-second AI summary of the match story, key wickets, milestone partnerships, and game momentum shifts.

### 2. 🔰 The Casual & Beginner Fan
* **Problem:** Intimidated by complicated acronyms, dense scorecards, and confusing terminology.
* **Solution:** Jargon-free scoreboard, friendly match stories, clickable cricket terms, and a dedicated **Cricket Explainer** supporting the **Top 10 IPL Fan Languages** (Hindi, Marathi, Tamil, Telugu, Kannada, Bhojpuri, Bengali, Gujarati, Malayalam, English).

### 3. 🎯 The Deep Tactical Fan
* **Problem:** Experienced fans want predictive insights, match momentum indicators, and head-to-head phase data.
* **Solution:** **Live Win Probability Bar**, batter vs. bowler phase statistics, run-rate progression, partnership breakdowns, and tactical AI question suggestions.

### 4. 🚗 The Busy / Commuting Driver
* **Problem:** Fans driving or multitasking cannot look at a screen safely.
* **Solution:** **Eyes-Off Radio Presenter Commentary** powered by in-browser speech synthesis. Energetically announces boundaries and wickets with natural punctuation pauses, prioritizes critical events, and suppresses chat inputs and distracting animations.

### 5. 🏟️ The In-Stadium Ground Companion
* **Problem:** Spectators at the stadium suffer from cellular congestion, screen glare under bright sunlight, and lag behind the live pitch action.
* **Solution:** Ultra-lightweight monochrome ticker, one-tap **Sunlight Readability Mode** (WCAG AAA high contrast), live DLS par score indicators, and instant DRS big-screen review synchronization.

### 6. 🌟 All-Rounder Mode
* **Problem:** Dedicated fans who want the complete experience all in one place.
* **Solution:** Comprehensive match hub featuring the live ball-by-ball timeline, streaming audio commentary, interactive Cricket Explainer, and the **Cricket Dost** AI assistant.

---

## 🤖 Cricket Dost — AI Match Assistant

Floating discreetly at the bottom-right corner, **Cricket Dost** provides real-time conversational intelligence:
* **Grounded Match Intelligence:** Powered by **Google Gemini 2.5 Flash** (with Groq Llama 3.3-70B fallback) to answer match questions with zero hallucination.
* **Context-Aware Answers:** Instantly calculates runs required, balls remaining, current vs. required run rate, and explains match situations.
* **Multilingual Interaction:** Responds fluently in Hindi, Marathi, Tamil, Telugu, and English.
* **Safety First:** Automatically disabled in *Busy / Driving* mode to ensure distraction-free driving.

---

## 🛠️ Advanced Engineering Innovations

* **Low-Data Mode with HTTP 304 ETags (Stage 5):** Emits MD5 ETags on data, timeline, and commentary endpoints. When match state is unchanged, the server returns `304 Not Modified`, reducing payload transfer to 0 bytes and saving battery on mobile networks.
* **Smart Timeline Filters (Stage 6):** Filter balls by **Boundaries (4s & 6s)**, **Wickets**, **Milestones**, and **Over Summaries**, plus an active player filter dropdown and score-at-event badges.
* **Personalised In-App Notifications (Stage 7):** In-app toast banner with sound controls and Web Notification API integration for wickets, boundaries, and results.
* **Spoiler Protection Delay (Stage 8):** Server-enforced retrospective time buffer (`0s`, `15s`, `30s`, `60s`, `120s`) allowing fans on delayed TV or stream broadcasts to sync the dashboard and hide future spoilers. Includes a one-click score privacy blur.

---

## 🚀 Quick Start Guide

### 1. Requirements
* Python 3.10 or higher
* Modern web browser (Chrome, Edge, Safari, Firefox)

### 2. Configure API Keys (Optional)
Copy `.env.example` to `.env` to enable Gemini AI Q&A:
```bash
cp .env.example .env
```
Add your private Gemini API key:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_backup_groq_key_here
```
*(Deterministic mode functions immediately even without an API key).*

### 3. Launch the Application
```powershell
python server.py
```
Open your browser and navigate to:
* **Fan Companion Dashboard:** [http://localhost:5000/fan](http://localhost:5000/fan)
* **Live JSON Data Feed:** [http://localhost:5000/fan/data](http://localhost:5000/fan/data)
* **Scoring Panel:** [http://localhost:5000/scoring](http://localhost:5000/scoring)

### 4. Run the Automated Test Suite
```powershell
pytest
```
*Over 340+ automated tests verify unit logic, HTTP endpoints, Playwright visual interactions, and audio synthesis (100% green).*

---

## 💻 Tech Stack & Architecture

* **Backend:** Python Threading HTTP Server & SQLite real-time timeline reconciler.
* **Frontend:** Responsive vanilla JavaScript, CSS custom properties, and semantic HTML5 with zero bloated frameworks.
* **AI & NLP:** Google Gemini 2.5 Flash, Groq API (Llama 3.3 70B), and regex-based deterministic intent classifier.
* **Audio Engine:** W3C Web Speech API (`SpeechSynthesis`) with dynamic priority queues.
* **Testing:** Pytest, Playwright (Chromium headless e2e tests), and Python `unittest`.
