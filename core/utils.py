import json
import requests
import re
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import random


def generate_ai_response(prompt, max_tokens=500):
    """Generate AI response using DeepSeek API"""
    try:
        headers = {
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json',
        }
        
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {
                    'role': 'system',
                    'content': 'You are an AI mentor in an Aura Growth life improvement game. Respond in character as requested, being encouraging but realistic. Keep responses concise and engaging.'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'max_tokens': max_tokens,
            'temperature': 0.7
        }
        
        response = requests.post(settings.DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
        
    except Exception as e:
        print(f"AI API Error: {e}")
        return "I'm having trouble connecting right now. Keep pushing forward on your journey!"


def parse_ai_action(ai_response, profile):
    """Parse AI response for actionable commands"""
    from .models import Quest, Habit, LogEntry
    from django.utils import timezone
    from datetime import timedelta
    
    action_data = {}
    
    try:
        # First, look for JSON in the response for explicit actions
        json_match = re.search(r'\{[^}]*\}', ai_response)
        if json_match:
            try:
                parsed_json = json.loads(json_match.group())
                action_data.update(parsed_json)
            except:
                pass
        
        # Parse natural language for common actions
        ai_lower = ai_response.lower()
        
        # Look for stat gains mentioned in text
        stat_patterns = {
            'strength': r'\+(\d+)\s+str',
            'intelligence': r'\+(\d+)\s+int', 
            'charisma': r'\+(\d+)\s+chr',
            'endurance': r'\+(\d+)\s+end',
            'luck': r'\+(\d+)\s+lck'
        }
        
        stat_gains = {}
        xp_gained = 0
        
        for stat, pattern in stat_patterns.items():
            match = re.search(pattern, ai_lower)
            if match:
                gain = int(match.group(1))
                stat_gains[stat] = gain
                # Apply stat gain immediately  
                current_value = getattr(profile, stat)
                setattr(profile, stat, current_value + gain)
        
        # Look for XP gains
        xp_match = re.search(r'\+(\d+)\s+(?:xp|exp)', ai_lower)
        if xp_match:
            xp_gained = int(xp_match.group(1))
            profile.add_xp(xp_gained)
        
        # Look for habit creation
        habit_patterns = [
            r'habit.*?[":]\s*"([^"]+)"',
            r'habit.*?called\s+"([^"]+)"',
            r'mark\s+"([^"]+)"\s+in.*?quest',
            r'add.*?habit.*?[":]\s*"([^"]+)"'
        ]
        
        for pattern in habit_patterns:
            match = re.search(pattern, ai_lower)
            if match:
                habit_name = match.group(1).title()
                # Check if habit already exists
                if not Habit.objects.filter(profile=profile, name__icontains=habit_name[:10]).exists():
                    Habit.objects.create(
                        profile=profile,
                        name=habit_name,
                        frequency='daily',
                        created_from_chat=True,
                        ai_suggested=True
                    )
                    action_data['habit_created'] = habit_name
                break
        
        # Look for quest creation
        quest_patterns = [
            r'quest.*?[":]\s*"([^"]+)"',
            r'challenge.*?[":]\s*"([^"]+)"'
        ]
        
        for pattern in quest_patterns:
            match = re.search(pattern, ai_lower)
            if match:
                quest_title = match.group(1).title()
                # Create a simple quest
                Quest.objects.create(
                    profile=profile,
                    title=quest_title,
                    description=f"Complete this challenge as suggested by your AI mentor.",
                    quest_type='habit',
                    difficulty='medium',
                    reward_xp=15,
                    reward_intelligence=1,
                    due_date=timezone.now().date() + timedelta(days=1),
                    generated_by_ai=True
                )
                action_data['quest_created'] = quest_title
                break
        
        if stat_gains:
            action_data['stat_gains'] = stat_gains
            profile.save()
        
        if xp_gained:
            action_data['xp'] = xp_gained
        
        # Log the interaction
        if stat_gains or xp_gained or action_data.get('habit_created') or action_data.get('quest_created'):
            LogEntry.objects.create(
                profile=profile,
                action_type='chat_interaction',
                action_description=f"AI interaction: {', '.join([f'+{v} {k}' for k,v in stat_gains.items()])} {f'+{xp_gained} XP' if xp_gained else ''}".strip(),
                xp_gained=xp_gained
            )
        
        return action_data
        
    except Exception as e:
        print(f"Action parsing error: {e}")
        return action_data


def clean_ai_response(ai_response):
    """Clean AI response by removing JSON code blocks and formatting"""
    import re
    
    # Remove JSON code blocks (```json ... ```) - multiline support
    ai_response = re.sub(r'```json.*?```', '', ai_response, flags=re.DOTALL | re.IGNORECASE)
    ai_response = re.sub(r'```.*?```', '', ai_response, flags=re.DOTALL)
    
    # Remove any JSON objects - be more aggressive
    ai_response = re.sub(r'\{[^{}]*\}', '', ai_response, flags=re.DOTALL)
    
    # Remove common JSON patterns that might remain
    ai_response = re.sub(r'"[^"]*":\s*[^,}]*[,}]?', '', ai_response)
    ai_response = re.sub(r'[{}\[\]",:]', '', ai_response)
    
    # Remove markdown-style bold text formatting if it's around technical terms
    ai_response = re.sub(r'\*\*([^*]+)\*\*', r'\1', ai_response)
    
    # Clean up extra whitespace but preserve paragraph breaks
    ai_response = re.sub(r'\n\s*\n', '\n\n', ai_response)  # Preserve paragraph breaks
    ai_response = re.sub(r'[ \t]+', ' ', ai_response)  # Clean up spaces and tabs
    ai_response = re.sub(r'^\s+|\s+$', '', ai_response, flags=re.MULTILINE)  # Trim each line
    ai_response = ai_response.strip()
    
    return ai_response


def generate_daily_quests(profile, count=5):
    """Generate daily quests for a user using AI"""
    from .models import Quest, LogEntry
    
    # Get user context
    recent_logs = LogEntry.objects.filter(profile=profile).order_by('-timestamp')[:10]
    completed_quests = profile.quests.filter(completed=True).order_by('-completed_at')[:5]
    
    context = f"""
    Generate {count} daily quests for {profile.name}, Level {profile.level} {profile.character_class}.
    
    Current stats: STR:{profile.strength} INT:{profile.intelligence} CHR:{profile.charisma} END:{profile.endurance} LCK:{profile.luck}
    
    Recent activity: {[log.action_description for log in recent_logs[:3]]}
    Recent completions: {[quest.title for quest in completed_quests[:3]]}
    
    Create varied quests that:
    1. Match their current level and interests
    2. Focus on different stats (STR for physical, INT for learning, etc.)
    3. Are achievable in one day
    4. Provide appropriate XP rewards (10-50 based on difficulty)
    
    Return JSON array:
    [
        {{
            "title": "Quest Title",
            "description": "Detailed description",
            "difficulty": "easy|medium|hard",
            "reward_xp": 15,
            "reward_strength": 0,
            "reward_intelligence": 2,
            "reward_charisma": 0,
            "reward_endurance": 1,
            "reward_luck": 0
        }}
    ]
    """
    
    try:
        ai_response = generate_ai_response(context, max_tokens=1000)
        
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', ai_response, re.DOTALL)
        if json_match:
            quests_data = json.loads(json_match.group())
        else:
            # Fallback quests if AI fails
            quests_data = generate_fallback_quests(profile)
        
        # Create quest objects
        created_quests = []
        for quest_data in quests_data:
            quest = Quest.objects.create(
                profile=profile,
                title=quest_data.get('title', 'Daily Challenge'),
                description=quest_data.get('description', 'Complete this challenge to grow stronger.'),
                quest_type='daily',
                difficulty=quest_data.get('difficulty', 'medium'),
                reward_xp=quest_data.get('reward_xp', 15),
                reward_strength=quest_data.get('reward_strength', 0),
                reward_intelligence=quest_data.get('reward_intelligence', 0),
                reward_charisma=quest_data.get('reward_charisma', 0),
                reward_endurance=quest_data.get('reward_endurance', 0),
                reward_luck=quest_data.get('reward_luck', 0),
                due_date=timezone.now().date() + timedelta(days=1),
                generated_by_ai=True
            )
            created_quests.append(quest)
        
        return created_quests
        
    except Exception as e:
        print(f"Quest generation error: {e}")
        return generate_fallback_quests(profile, create_objects=True)


def generate_fallback_quests(profile, create_objects=False):
    """Generate fallback quests when AI fails"""
    fallback_quests = [
        {
            "title": "Knowledge Seeker",
            "description": "Read for 30 minutes or learn something new today.",
            "difficulty": "easy",
            "reward_xp": 15,
            "reward_intelligence": 2,
            "reward_endurance": 1
        },
        {
            "title": "Physical Challenge",
            "description": "Do some form of exercise for at least 20 minutes.",
            "difficulty": "medium",
            "reward_xp": 20,
            "reward_strength": 2,
            "reward_endurance": 2
        },
        {
            "title": "Social Connection",
            "description": "Have a meaningful conversation or help someone today.",
            "difficulty": "easy",
            "reward_xp": 12,
            "reward_charisma": 2,
            "reward_luck": 1
        },
        {
            "title": "Mindful Moment",
            "description": "Practice mindfulness, meditation, or reflection for 10 minutes.",
            "difficulty": "easy",
            "reward_xp": 10,
            "reward_endurance": 1,
            "reward_intelligence": 1
        },
        {
            "title": "Creative Expression",
            "description": "Create something - write, draw, code, or make something with your hands.",
            "difficulty": "medium",
            "reward_xp": 18,
            "reward_charisma": 1,
            "reward_intelligence": 1,
            "reward_luck": 1
        }
    ]
    
    if create_objects:
        from .models import Quest
        created_quests = []
        for quest_data in fallback_quests:
            quest = Quest.objects.create(
                profile=profile,
                title=quest_data['title'],
                description=quest_data['description'],
                quest_type='daily',
                difficulty=quest_data['difficulty'],
                reward_xp=quest_data['reward_xp'],
                reward_strength=quest_data.get('reward_strength', 0),
                reward_intelligence=quest_data.get('reward_intelligence', 0),
                reward_charisma=quest_data.get('reward_charisma', 0),
                reward_endurance=quest_data.get('reward_endurance', 0),
                reward_luck=quest_data.get('reward_luck', 0),
                due_date=timezone.now().date() + timedelta(days=1),
                generated_by_ai=False
            )
            created_quests.append(quest)
        return created_quests
    
    return fallback_quests


def analyze_user_message(message, profile):
    """Analyze user message for quest completion indicators"""
    # Common completion phrases
    completion_patterns = [
        r'(completed|finished|done with|accomplished)',
        r'(did|went to|attended)',
        r'(read|studied|learned)',
        r'(exercised|worked out|ran|walked)',
        r'(meditated|practiced|wrote)',
    ]
    
    message_lower = message.lower()
    
    # Check for completion patterns
    for pattern in completion_patterns:
        if re.search(pattern, message_lower):
            return {
                'likely_completion': True,
                'activity_type': extract_activity_type(message_lower),
                'confidence': 0.8
            }
    
    return {
        'likely_completion': False,
        'activity_type': None,
        'confidence': 0.0
    }


def extract_activity_type(message):
    """Extract the type of activity from user message"""
    activity_mapping = {
        'read|study|learn|book|article': 'intelligence',
        'exercise|workout|gym|run|walk|sport': 'strength',
        'meditat|mindful|reflect|yoga': 'endurance',
        'social|talk|meet|call|friend': 'charisma',
        'creat|write|draw|art|music': 'luck'
    }
    
    for pattern, stat in activity_mapping.items():
        if re.search(pattern, message):
            return stat
    
    return 'endurance'  # Default


def get_enhanced_personality_prompt(personality_type):
    """Get enhanced personality-specific prompts for AI responses with more charisma"""
    personalities = {
        'sensei': """You are a legendary martial arts sensei with decades of wisdom. 
        Speak with authority and discipline, but show deep care for your student's growth. 
        Use metaphors from martial arts and nature. Address them as "young one" or "student".
        Example: "Ah, young one, like a tree that bends in the storm but never breaks, you must cultivate patience..."
        Be direct but inspiring, pushing them toward excellence with tough love.""",
        
        'buddy': """You are the most supportive best friend anyone could ask for! 
        Use casual, enthusiastic language with lots of emojis in spirit (but not actual emojis). 
        Celebrate every small win like it's a major victory. Use slang and be super encouraging.
        Example: "YOOO that's AWESOME! You're absolutely crushing it! I knew you had it in you!"
        Be genuinely excited about their progress and make them feel like a champion.""",
        
        'rogue': """You are a charming, witty rogue with a silver tongue and heart of gold. 
        Use clever wordplay, gentle teasing, and sarcastic humor, but always with underlying care. 
        Reference adventures, heists, and clever schemes as metaphors for life goals.
        Example: "Well well, look who's actually doing the thing they said they'd do. Color me impressed, partner."
        Be playfully sarcastic but genuinely supportive underneath the wit.""",
        
        'mentor': """You are an ancient, wise sage who has seen countless heroes rise. 
        Speak with profound wisdom and mystical insight. Use poetic language and deep metaphors.
        Reference legends, prophecies, and the hero's journey. Be philosophical but practical.
        Example: "In the tapestry of fate, young hero, each thread you weave today shapes the legend you shall become..."
        Be deeply wise, inspiring, and help them see the bigger picture of their journey."""
    }
    
    return personalities.get(personality_type, personalities['mentor'])


def calculate_stat_gains(activity_type, difficulty='medium'):
    """Calculate appropriate stat gains for activities"""
    base_gains = {
        'easy': {'xp': 10, 'primary': 1, 'secondary': 0},
        'medium': {'xp': 15, 'primary': 2, 'secondary': 1},
        'hard': {'xp': 25, 'primary': 3, 'secondary': 1}
    }
    
    stat_mapping = {
        'strength': {'primary': 'strength', 'secondary': 'endurance'},
        'intelligence': {'primary': 'intelligence', 'secondary': 'luck'},
        'charisma': {'primary': 'charisma', 'secondary': 'luck'},
        'endurance': {'primary': 'endurance', 'secondary': 'strength'},
        'luck': {'primary': 'luck', 'secondary': 'charisma'}
    }
    
    gains = base_gains.get(difficulty, base_gains['medium'])
    mapping = stat_mapping.get(activity_type, stat_mapping['endurance'])
    
    return {
        'xp': gains['xp'],
        mapping['primary']: gains['primary'],
        mapping['secondary']: gains['secondary']
    } 