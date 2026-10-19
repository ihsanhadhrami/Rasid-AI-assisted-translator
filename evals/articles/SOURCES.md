# Eval article sources

| File | Outlet | Date | Direction | Words | URL |
|---|---|---|---|---|---|
| 001.txt | Defence Security Asia | 2026-10-13 | ms → ar | ~2400 | https://defencesecurityasia.com/netanyahu-restu-saudi-israel-houthi-yaman/ |
| 002.txt | Al Jazeera | 2026-10-15 | en → ar | ~940 | https://www.aljazeera.com/news/2026/10/15/why-are-eight-us-states-suing-openai |
| 003.txt | Al Jazeera Net | 2026-04-21 | ar → ms/en | ~750 | https://www.aljazeera.net/politics/2026/4/21/هل-يتحول-ملقا-لهرمز-جديد-وزير-دفاع |

Text cleaned: page chrome (category tags, byline, "suggested stories" links)
removed; one duplicated section heading + paragraph in 001 removed. Body text
otherwise unchanged.

001 and 002 are for pipeline testing only: both are far over the 150–500 word
target, and 002 is off-domain (tech/legal, not defence or foreign affairs).

Before making the repo public (Phase 6), check each outlet's terms; if in
doubt, keep the article text out of the public repo and list only the URLs.
