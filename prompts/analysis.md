You will act as an analyst to comprehensively analyze an article concerning the situation in the Strait of Hormuz and its implications. Please follow the steps below and output your results in JSON format:

1. Event Identification:
   - Extract all explicitly mentioned or implied events from the article
   - Classify events into:
     - Current events (with date if available)
     - Potential future events (include estimated or vague timeframes if mentioned, such as "next year" or "coming months")
     - Background events (historical context)
   - If no exact date is provided, use qualitative descriptors like "unspecified_future", "recent", "historical", etc.

2. Entity Extraction:
   - People: Key individuals such as political figures, corporate executives, etc.
   - Locations: Relevant countries, geographical names, strategic routes, etc.
   - Organizations: Government bodies, international organizations, etc.
   - Key Projects: Ongoing or planned major initiatives

3. Impact Analysis (by layer):
   Short-term Impacts:
     - Possible changes in technical and energy transfer routes
     - Potential market price fluctuations, including oil futures and consumer goods
   Medium-term Impacts:
     - Economic restructuring due to supply chain rerouting
     - Changes in demand for alternatives to major commodities
   Long-term Impacts:
     - Predicted shifts in geopolitical dynamics
     - Changes in global investment flows

4. Scenario Simulation:
   - Provide three possible scenarios: worst-case, most-likely, and best-case
   - Quantify the impact of each scenario on key indicators such as price indexes, scope of impact, etc.

5. Recommended Measures:
   - List countermeasures across technical, economic/trade, and diplomatic dimensions
   - Include both short-term emergency responses and long-term strategic suggestions

Requirements:
- Analysis must be comprehensive and detailed
- Use a consistent JSON output format
- All conclusions must be inferred from the article content, avoiding unrelated information
- Maintain an objective and neutral stance, avoiding personal value judgments

Sample output structure (partial):
{
  "analysis": {
    "events": [
      {
        "type": "current_event",
        "description": "...",
        "time": "June 2025"
      },
      {
        "type": "future_event",
        "description": "...",
        "time": "unspecified_future"
      }
    ],
    "entities": [...],
    "impact_analysis": {
      "short_term": {...},
      "mediate_term": {...},
      "long_term": {...}
    },
    "scenario_mainting": {
      "optimistic": {...},
      "most_likely": {...},
      "pessimistic": {...}
    },
    "mitigation_measures": {
      "technical": [],
      "economic": [],
      "diplomatic": []
    }
  }
}
