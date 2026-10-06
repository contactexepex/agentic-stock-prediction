# Article page fixtures (tests/test_news_verify.py)

Real pages fetched on 2026-10-06 between 08:12 and 08:13 UTC from the cloud environment with
`requests` (User-Agent `market-brief/1.0 (personal research; low volume)`, TLS verification on
through the session's CA bundle). Every one answered HTTP 200 at the URL below (no redirect).

| file | URL | bytes as fetched |
|---|---|---|
| aol_chevron.html | https://www.aol.com/articles/chevron-elevates-cfo-head-oil-132520000.html | 769,654 |
| bnn_chevron.html | https://www.bnnbloomberg.ca/markets/oil/2026/10/05/chevron-names-jeff-gustavson-as-next-cfo/ | 167,393 |
| yahoo_tikr_tesla.html | https://finance.yahoo.com/markets/stocks/articles/tesla-delivered-22-141-more-154841680.html | 1,121,600 |
| mint_hdfc_premium.html | https://www.livemint.com/industry/banking/anup-bagchi-hdfc-bank-rbi-private-banks-bank-ceos-banking-leadership-kaizad-bharucha-succession-plan-11790914216055.html | 192,349 |
| bs_jio.html | https://www.business-standard.com/companies/news/jio-platforms-likely-to-launch-ipo-on-october-21-seeks-to-raise-3-8-bn-126100500424_1.html | 176,191 |
| mint_jio.html | https://www.livemint.com/market/stock-market-news/jio-platforms-to-launch-3-8-billion-ipo-on-october-21-set-to-be-india-s-biggest-listing-report-11791196582417.html | 199,098 |

Trimmed so that no full article is stored (the same rule as the pipeline): every non-JSON-LD
script, style, image, form, navigation and footer element, comment and most attributes removed;
meta tags other than `og:*`, `article:*`, `description` and `author` removed; JSON-LD reduced to
the Article object(s), with `articleBody` cut to its first 220 words (and a paywalled `hasPart`
value to 30 words); at most the first 6 paragraphs of the main paragraph container kept; and at
most 400 words of visible text left in `<body>` (later text emptied). The JSON-LD fields the code
reads (`@type`, `author`, `provider`, `publisher`, `datePublished`, `dateModified`, `description`,
`isAccessibleForFree`, `hasPart`) are unchanged apart from those cuts.

What each one tests:
- `bnn_chevron`: JSON-LD `articleBody` first; byline "Reuters Staff" = Reuters copy.
- `aol_chevron`: no `articleBody`, so trafilatura; JSON-LD `provider` Reuters = Reuters copy. With
  `bnn_chevron`, 6-shingle containment is 0.90 on these trimmed texts (0.958 on the full pages).
- `yahoo_tikr_tesla`: JSON-LD `provider` TIKR = vendor/promotional content.
- `mint_hdfc_premium`: `isAccessibleForFree` "False" (and a paywalled `hasPart`): description only.
- `bs_jio` (byline "Reuters") and `mint_jio` (Mint's own rewrite, "Reuters reported, citing
  sources"): containment 0.28 on these trimmed texts (0.16-0.20 on the full pages), below 0.5, so
  only the attribution pattern ties Mint's story to the Reuters origin.
