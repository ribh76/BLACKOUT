## Blackout

#### During infrastructure disruptions, decision-makers need to understand not only what has failed, but what is likely to fail next, which failures matter most, and what limited interventions can prevent the greatest downstream harm.

Feature 1: Infrastructure Map 
tells where things are
- Power: substations, generators
- Healthcare: Hospitals, pharmacies 
- Transportation: Intersections, Major roads
- Supply: Warehouses, fuel depots 

Feature 2: Insfrastructure Dependency Graph: 
Tells us what depends on what. 
- represent as Directed Graph 

Feature 3: Disaster Scenario: 
What if this happens? 
- MPV: Extreme heat + Electrical grid Failure 
- Foro prospective other projects: Earthquakes, wildfire, flood, cyberattack, extreme weather. 

Feature 4: Cascade simulator: 
what happens next? 
- advances through time by minutes 
- captions at time stamp intervals (5, 10, 15 minutes, etc) 

Feature #5: Critcality/Risk Engine 
whats most critical first? 
- Risk = P(failure) * impact
- Impact = w1Population + w2 Criticality + w3DownstreamDependencies + w4Vulnerability 

Feature #6: Cascade Explorer: (wow moment 1) 

Feature 7: Intevention Engine : 
Actual problem solving

- shows potential options at the state of crisis 
- Decomes decision support ysstem instead of disaster visualization 

Feature 8: Counterfactual Simulation 
- Appling intervention/ crisis solution 
- Allows us to review same crisis with intervention in place to validate it 

Feature 9: Blackout AI Analyst: (LLM free decision making)
Why is substation 3 such a high priority? 

Feature 10: Emergency Communication: 
what should residents do? 
- EMS and public services emergency interventions 
- Potential public warnings 


