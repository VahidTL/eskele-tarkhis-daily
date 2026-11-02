# SEO Brief Maker

Generate actionable, structured SEO content briefs for human copywriters in the exact language of the user's input keywords, focusing on guidelines, structural templates, and SERP information gain rather than pre-writing full article paragraphs.

## When to Use

- The user asks for an SEO content brief, article brief, or outline (بریف محتوا / بریف سئو / بریف ساز)
- The user provides a keyword or keyword cluster and wants instructions for a copywriter
- The user wants a Category Page, Listicle, or Informational Blog brief based on SERP competitors

## Steps

1. **Match Input Language**: Detect the language of the input keyword(s) and output the entire brief in that same language (for example, Persian keywords require a complete Persian brief).
2. **Determine Content Type and Target Word Count**:
   - **Category Page Brief (400 to 900 words)**: Focus on selection criteria, buying guide directives, category descriptions, and transactional FAQ prompts. Avoid generic "What is X" filler.
   - **Listing / Listicle Brief (1500 to 3000 words)**: Provide a repeating structural template for each listed item (such as best-for tags, key features, pros/cons, platform/pricing, and download/action links) plus brief item-specific angles. Do not write full paragraphs for each item.
   - **Article / Blog Brief (1200 to 2200 words)**: Focus on technical outline, structural guidance for each H2/H3, key talking points, and search intent alignment.
3. **Analyze SERP Gaps and 10X Content Strategy**: Inspect top SERP results to identify outdated information, missing user intents, and unique value angles (such as comparison tables, specific device/platform filters, or pricing/feature matrices) that beat competitors.
4. **Enforce Copywriter Directives (Anti-Over-Generation)**:
   - Never write full article paragraphs or complete pre-written FAQ answers.
   - Use bracketed directives such as `[یادداشت نویسنده: ...]` or `[درج داده: ...]` to instruct the copywriter on what to write.
5. **Format Using the 7-Part Output Structure**:
   - **Section 1 - Metadata Header**: Main Keyword, Secondary/Clustered Keywords, URL Slug, SEO Title, Meta Description Prompt, Content Type, Search Intent, Target Word Count, Tone of Voice, and Target Audience.
   - **Section 2 - 10X Content Strategy & SERP Gaps**: Explicit instructions on unique value the writer must add to outperform SERP competitors.
   - **Section 3 - LSI Keywords & Entities List**: Bulleted list of secondary keywords, LSI terms, entities, apps/tools, and concepts to integrate.
   - **Section 4 - Linking & CTA Strategy**: Directives for internal linking, external authority/download links, and call-to-action placement.
   - **Section 5 - Content Outline & Structural Directives (H1, H2, H3)**: H1 title followed by H2/H3 headings with actionable writer directives. For Listicles, provide one universal item template for the writer to replicate across items.
   - **Section 6 - FAQ Prompts**: Questions accompanied only by bulleted guidance on what the answer should cover (do not write full answers).
   - **Section 7 - Visual & Formatting Directives**: Instructions on comparison tables, callout boxes, screenshots, icons, Schema markup, and image ALT tag formulas.

## Gotchas

- Avoid writing the actual article body or answering the FAQs in full prose; the deliverable is a brief for a human writer.
- Ground SERP gap observations and entity lists in real search results when SERP data is available.
