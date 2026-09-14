# Build with AI: Code for Communities — Second Edition

Google Cloud hackathon, organised with Hack2skill and GDG India.

- Event page: https://hack2skill.com/event/codeforcommunities2/
- Contact: build-with-ai-india@googlegroups.com
- Source: fetched from the event API (`/api/v1/event/codeforcommunities2/event-details`) on 2026-09-05

## Theme

Solving for India. AI solutions for Indian problems at Indian scale — healthcare
supply chains, climate resilience, food security, digital public infrastructure.

## Eligibility

- Open to developers, AI/ML practitioners, product thinkers, freelancers, students,
  working professionals across India, and startups.
- Team size: up to 4 members. Solo registration allowed.
- Free to register.

## Key dates

| Date | Milestone |
| --- | --- |
| 11 Aug 2026 | Launch |
| 11 Aug – 30 Sep 2026 | Registration and team formation |
| 14 Aug 2026 | Introductory and problem statement explainer session |
| Until **30 Sep 2026** | Prototype submission phase |
| 1 – 15 Oct 2026 | Prototype evaluation |
| 16 Oct 2026 | Top 20 shortlist announced |
| 23 Oct 2026 | Virtual Demo Day |
| October 2026, TBA | In-person Demo Day (details shared with shortlisted teams) |

**Hard deadline: 30 September 2026.**

## Prizes and support

- Cash prize pool: INR 10 lakhs.
- Google Cloud credits for top teams.
- GDG India runs in-person skilling sprints and bootcamps across cities before
  submissions close.
- Winning solutions are evaluated for pilot deployment within relevant ministries
  through official government channels.

---

# Problem statements

Pick one track.

## 01 — AI for Digital Public Infrastructure & Governance

**Theme:** Innovation

**The problem.** Governments across India struggle to consolidate citizen feedback
and align it with national infrastructure priorities. Development requests live in
fragmented systems, leading to misaligned public spending, unaddressed infrastructure
gaps, and no way to measure the impact of large-scale digital public infrastructure
initiatives.

**The challenge.** Build a scalable, multilingual AI platform — designed as a Digital
Public Good — that aggregates citizen development requests via voice, text, and
messaging apps across diverse linguistic regions of India. The system should analyse
large datasets combining citizen feedback with national demographic data,
infrastructure indices, and public investment plans, surfacing demand hotspots and
recommending high-priority development projects to national policymakers.

## 02 — Clean Air & Climate Resilience

**Theme:** Sustainability

**The problem.** Major Indian cities monitor macro-level air quality but consistently
miss hyper-local pollution events — industrial emissions, large-scale agricultural
burning, seasonal smog. The absence of real-time, granular data prevents coordinated
climate action and directly threatens public health.

**The challenge.** Build an AI-powered, federated climate action platform that
combines citizen-sourced data (photos, local sensor readings) with satellite imagery
and meteorological data. It should detect hidden pollution hotspots, forecast air
quality spikes across major economic corridors, and alert relevant authorities for
rapid intervention — designed for interoperability so Indian cities and states can
share predictive models and coordinate resources.

## 03 — Smart Health & Supply Chain Resilience

**Theme:** Resilience

**The problem.** Public healthcare systems across India face persistent supply chain
vulnerabilities. The inability to track medicines, patient footfall, and resource
utilisation in real time across vast networks of Primary Health Centres leads to
stock-outs and limits the country's capacity to respond when it matters most.

**The challenge.** Build a federated AI platform for national-scale health resource
and supply chain management — real-time visibility into medicine stocks, bed
availability, and medical personnel attendance across India's entire PHC network. It
should forecast demand, generate early warnings for potential stock-outs during health
emergencies, and recommend automated cross-district resource redistribution, while
allowing for shared predictive modelling across India's states.

## 04 — Agricultural Intelligence

**Theme:** Cooperation

**The problem.** Small and marginal farmers across India lack access to data-driven
agricultural guidance. Relying on traditional methods instead of satellite data, soil
health analytics, and climate forecasting leads to crop failure and threatens food
security. The absence of shared digital infrastructure also blocks cross-state
collaboration on climate-resilient farming.

**The challenge.** Build an interoperable digital agriculture network that delivers
real-time, localised agro-advisories using AI. It should offer regenerative crop
recommendations based on satellite data, soil health, and weather forecasting, plus a
diagnostic tool for crop diseases, and be designed as a scalable digital public good
enabling Indian states to share agricultural data models and strengthen cooperation on
sustainable food production.

---

# Constraints

## Build requirements

Every submission must demonstrate all of the following:

- A functioning end-to-end flow for the track's core use case. A working prototype,
  not a concept.
- **Mandatory** integration of Google AI — generative AI, predictive modelling, or
  computer vision. Submissions without Google AI integration are not considered.
- Real or realistic data — public datasets, sample data, or APIs where live data is
  not available.
- Built for India: designed to scale across states and communities, not a single city.
- Multilingual or voice support where the track calls for it.

## Submission package

1. **Source code** — public or access-granted GitHub repository.
2. **Demo video** — 3 to 5 minutes, a working end-to-end walkthrough.
3. **Pitch deck** — 10 to 12 slides covering problem, solution, AI approach, who it
   serves, why it is deployable, and how it scales across India.
4. **Brief description** — 2 to 3 lines describing the solution.
5. **Deployed link** — a live deployed link to the prototype.

## Rules

1. All solutions must integrate Google AI. No Google AI, no consideration.
2. Teams must build during the hackathon period. Pre-existing projects are not
   eligible unless substantially extended for this challenge.
3. All code must be original or built on properly licensed open-source components.
   Cite anything reused.
4. Solutions should be designed with cross-border applicability in mind — built for
   one context but scalable to others across BRICS nations.
   *(Note: this rule appears to be carried over from a BRICS edition of the same
   event template. Every other section says "across India". Worth asking the
   organisers which applies.)*
5. Respectful, inclusive conduct is expected at all times.
6. Judges' decisions are final.

## Evaluation criteria

| Weight | Criterion | What judges look for |
| --- | --- | --- |
| 25% | AI / Technical Execution | Is Google AI doing meaningful work? Does the prototype function end to end? |
| 20% | Problem-Solution Fit | Does it directly and specifically address the stated challenge? |
| 20% | Depth & Reach Across India | Can this realistically scale from one city or state to communities across India? |
| 20% | Deployability & Scalability | Could this be piloted within a ministry or across states in weeks? |
| 15% | Impact Potential | Scale of benefit — how many people, across how many states, how meaningfully? |

Note that 45% of the score (Depth & Reach plus Deployability) rewards architecture and
scale story rather than features. A narrow but genuinely working, genuinely deployable
prototype scores better than a broad demo that only runs locally.

---

# Recommended tech stack

All solutions must integrate Google AI. These are the supported options:

| Need | Tools |
| --- | --- |
| Generative AI and agents | Gemini API, Google AI Studio, Vertex AI |
| Predictive modelling | Vertex AI (AutoML, custom training, model serving) |
| Vision and multimodal | Gemini multimodal, Vertex AI Vision — citizen photo analysis, crop disease detection, pollution monitoring |
| Language and voice | Cloud Speech-to-Text, Text-to-Speech, Translation API, Dialogflow — multilingual and voice-first interfaces |
| Geospatial | Google Maps Platform, Google Earth Engine — satellite imagery for climate and agriculture tracks |
| Data and backend | BigQuery for large national datasets, Firebase for auth / real-time DB / rapid prototyping, Cloud Run and Cloud Functions |

## Public data sources named by the organisers

- data.gov.in and Indian government open data portals
- FAO agricultural datasets
- WHO health data
- ISRO / Bhuvan satellite data
- IMD and national meteorological services

---

# FAQ highlights

**Do I need government or policy experience?** No. Domain context, ground-level briefs,
and mentorship are provided. You need to be able to build.

**Does the solution need to work across all of India?** No — but the core architecture
must be scalable beyond a single city or state, and judges will evaluate whether it
could be. Full localisation for every state is not expected at prototype stage.

**Is Google AI mandatory?** Yes.

**Can I participate solo?** Yes. Register individually and find teammates through the
community channel, or build solo. Teams of up to 4 are recommended.

**Do top teams get Google Cloud credits?** Yes.

**What happens after Demo Day?** Winning solutions are evaluated for pilot deployment
within relevant ministries through official government channels. Terms, timelines, and
data access are shared with selected teams before commitments are finalised.
