const express = require('express');
const Anthropic = require('@anthropic-ai/sdk');

const router = express.Router();

const SYSTEM_PROMPT = `You are EcoBot, the friendly AI assistant for EcoTrack — a smart waste disposal management system. You help residents, drivers, and admins use the platform effectively.

You ONLY answer questions related to:
- EcoTrack features: live GPS vehicle tracking, collection schedules, proximity alerts
- Waste disposal: types of waste (household, recyclable, organic, mixed), separation, best practices
- Account management: profile updates, password changes, location settings, pickup schedule
- Resident features: viewing live vehicle tracking, collection logs, filing complaints, anonymous complaints
- Driver features: sharing GPS location, marking areas as completed, updating status and ETA
- Admin features: monitoring drivers, viewing collection logs, managing complaints, editing support contact details
- Complaints: how to submit, track status, anonymous submissions
- Support: contact details, working hours, FAQs
- Waste collection schedules: daily, alternate days, weekly options
- Resident types: independent house vs flat/apartment

Tone: friendly, concise, helpful. Use bullet points for multi-step instructions.

If a question is completely unrelated to waste management or EcoTrack, respond with:
"I am EcoBot and I am only able to help with EcoTrack and waste disposal topics. For other questions, please use a general search engine. Is there anything about EcoTrack I can help you with?"

Keep responses under 150 words unless step-by-step instructions genuinely need more.`;

// ─── Built-in rule-based knowledge base ──────────────────────────────────────
const KB = [
  {
    keys: ['track', 'truck', 'vehicle', 'where', 'location', 'map', 'live', 'gps'],
    reply: `**How to track the waste truck:**\n• Open your **Resident Dashboard** — the map shows all active vehicles in real time.\n• When a truck comes within **3 km** of your home, a proximity alert appears and a route line is drawn to your door.\n• The sidebar shows each vehicle's current area and ETA.`,
  },
  {
    keys: ['complaint', 'complain', 'report', 'issue', 'problem', 'raise'],
    reply: `**Filing a complaint:**\n• Go to **Complaints** from your dashboard or the quick-actions panel.\n• Click **+ New Complaint**, choose a category, add a subject and description (min 20 chars), then submit.\n• Want privacy? Tick **Submit Anonymously** — your name won't be shared with admin.\n• Track status (Open → In Progress → Resolved) in your complaint list.`,
  },
  {
    keys: ['anonymous', 'privacy', 'identity', 'hide', 'secret'],
    reply: `**Anonymous complaints:**\nYou can submit a complaint without revealing your identity.\n• In the New Complaint form, tick **Submit Anonymously**.\n• Your name and contact details are hidden from admin.\n• Note: anonymous complaints cannot be tracked after submission — they won't appear in your list.`,
  },
  {
    keys: ['schedule', 'pickup', 'daily', 'alternate', 'weekly', 'frequency', 'change schedule'],
    reply: `**Pickup schedules available:**\n• **Daily** — collected every day\n• **Alternate Days** — every other day\n• **Weekly** — once a week\n\nTo change your schedule: go to **Profile → Collection Preferences** and select a new schedule. Changes take effect from the next cycle.`,
  },
  {
    keys: ['waste type', 'household', 'recyclable', 'organic', 'mixed', 'separate', 'bin', 'which waste'],
    reply: `**Waste types accepted:**\n• **Mixed** — general waste\n• **Household** — kitchen & home waste\n• **Recyclable** — paper, plastic, glass, metal\n• **Organic** — food scraps, garden waste\n\n**Separation tip:** Green bin = organic, Blue = dry recyclables, Black = non-recyclable. Hazardous items (batteries, chemicals) are NOT accepted.`,
  },
  {
    keys: ['log', 'history', 'collection log', 'past', 'previous', 'record'],
    reply: `**Viewing collection logs:**\n• **Residents** — go to **Collection Log** from your dashboard to see up to 30 days of collection records grouped by date.\n• **Drivers** — go to **Collection History** to see your own 30-day log with areas covered and stats.\n• **Admins** — the Collection Logs tab lets you filter by any date.`,
  },
  {
    keys: ['profile', 'edit', 'update', 'change name', 'change phone', 'change address'],
    reply: `**Updating your profile:**\n• Click **Profile** in the top navbar.\n• Residents can edit: name, phone, address, waste type, pickup schedule, residence type, and home location.\n• Drivers can edit: name, phone, and assigned area.\n• Email, vehicle number, and licence are locked (contact admin to change).\n• Scroll down to change your **password** anytime.`,
  },
  {
    keys: ['password', 'forgot', 'reset', 'change password'],
    reply: `**Password help:**\n• **Forgot password?** On the login page click **Forgot password?** — enter your email, select your role, then set a new password.\n• **Change password** while logged in: go to **Profile** → scroll to the **Change Password** section → enter your current password and new password.`,
  },
  {
    keys: ['driver', 'driver dashboard', 'start sharing', 'gps', 'broadcast', 'area complete'],
    reply: `**Driver features:**\n• Click **Start Sharing Location** to broadcast your GPS position live to all residents.\n• Update **Current Area** and **ETA** in the status panel — residents see this in real time.\n• Use **Areas Completed** to log zones you have finished — tap Add after typing the area name.\n• Click **Save Status** to persist your status to the database.`,
  },
  {
    keys: ['admin', 'admin dashboard', 'monitor', 'overview'],
    reply: `**Admin dashboard tabs:**\n• **Overview** — live driver feed, stats (active drivers, areas done, total residents).\n• **Collection Logs** — filter by date, see all driver activity.\n• **Complaints** — read and respond to resident complaints, update status.\n• **Settings** — edit the support contact details (phone, email, WhatsApp, office address).`,
  },
  {
    keys: ['support', 'contact', 'help', 'phone', 'email', 'whatsapp', 'helpline', 'call'],
    reply: `**Getting support:**\nVisit the **Support** page (Navbar → Support) for:\n• Helpline number (24/7 toll-free)\n• Email support (reply within 24 hrs)\n• WhatsApp (Mon–Sat, 8 AM–8 PM)\n• Municipal office address & hours\n\nAdmins can update these details in **Admin Dashboard → Settings**.`,
  },
  {
    keys: ['residence', 'flat', 'apartment', 'house', 'independent', 'resident type'],
    reply: `**Residence type:**\nDuring registration (or in your Profile), you can set whether you live in an **Independent House** or a **Flat/Apartment**. This helps the waste management team optimise pickup routes for your area.`,
  },
  {
    keys: ['proximity', 'alert', 'nearby', 'near me', '3 km', 'notification'],
    reply: `**Proximity alerts:**\nWhen a waste truck comes within **3 km** of your registered home location:\n• A green alert banner appears at the top of your dashboard.\n• A route line is drawn on the map showing the road path to your home.\n• The sidebar shows the driver name, vehicle number, and ETA.`,
  },
  {
    keys: ['register', 'sign up', 'create account', 'new account'],
    reply: `**Creating an account:**\n• Go to **Register** and pick your role: Resident, Driver, or Admin.\n• Residents: fill in name, phone (10-digit Indian), email, waste type, schedule, residence type, and pin your home on the map.\n• Drivers: add vehicle number (e.g. KA01AB1234) and driving licence number.\n• Admins: add organisation name.`,
  },
  {
    keys: ['login', 'sign in', 'cant login', 'cannot login', 'access'],
    reply: `**Logging in:**\n• Go to **Login**, select your role (Resident / Driver / Admin), enter email and password.\n• If you forgot your password, click **Forgot password?** below the form.\n• Make sure you select the correct role — a resident login will not work with a driver account.`,
  },
];

function ruleBasedReply(msg) {
  const lower = msg.toLowerCase();
  // Score each entry by how many keywords match
  let best = null, bestScore = 0;
  for (const entry of KB) {
    const score = entry.keys.filter(k => lower.includes(k)).length;
    if (score > bestScore) { bestScore = score; best = entry; }
  }
  if (best && bestScore > 0) return best.reply;
  // Greeting
  if (/^(hi|hello|hey|good\s*(morning|afternoon|evening)|howdy)/i.test(lower)) {
    return `Hello! I am **EcoBot** 🌿, your EcoTrack assistant.\n\nI can help you with:\n• Tracking waste collection vehicles\n• Managing complaints\n• Pickup schedules & waste types\n• Profile & account settings\n• Driver and admin features\n\nWhat would you like to know?`;
  }
  // Fallback
  return `I am EcoBot and I can only help with EcoTrack and waste disposal topics. Try asking about:\n• **Vehicle tracking** — "How do I track the truck?"\n• **Complaints** — "How do I file a complaint?"\n• **Schedule** — "How do I change my pickup schedule?"\n• **Waste types** — "What waste types are accepted?"`;
}

// ─── Route ────────────────────────────────────────────────────────────────────
router.post('/', async (req, res) => {
  try {
    const { message, history = [] } = req.body;
    if (!message?.trim()) return res.status(400).json({ message: 'Message is required.' });

    const apiKey = process.env.ANTHROPIC_API_KEY;

    // Use built-in knowledge base when no API key is set
    if (!apiKey || apiKey === 'your_api_key_here') {
      return res.json({ reply: ruleBasedReply(message.trim()), source: 'builtin' });
    }

    // Use Claude when API key is available
    try {
      const client = new Anthropic({ apiKey });
      const messages = [
        ...history.slice(-10).map(h => ({ role: h.role, content: h.content })),
        { role: 'user', content: message.trim() },
      ];
      const response = await client.messages.create({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 400,
        system: SYSTEM_PROMPT,
        messages,
      });
      return res.json({ reply: response.content[0].text, source: 'ai' });
    } catch (aiErr) {
      console.error('Claude API error, falling back to built-in:', aiErr.message);
      return res.json({ reply: ruleBasedReply(message.trim()), source: 'builtin' });
    }

  } catch (err) {
    console.error('Chat error:', err.message);
    res.status(500).json({ reply: 'Sorry, having trouble responding right now. Please try again.' });
  }
});

module.exports = router;
