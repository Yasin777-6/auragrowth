from celery import shared_task
import json
from django.utils import timezone
from .models import Profile, AIResponse, Quest
from .utils import generate_ai_response, generate_daily_quests


@shared_task
def enhance_character_with_ai(profile_id, name, role, interests, goal):
    """Background task to enhance character with AI after fast registration"""
    try:
        profile = Profile.objects.get(id=profile_id)
        
        # Generate enhanced character data with AI
        ai_prompt = f"""
        Analyze this new RPG player and enhance their character:
        Name: {name}
        Role: {role}
        Interests: {', '.join(interests) if interests else 'General improvement'}
        Goal: {goal}
        
        Current class: {profile.character_class}
        Current stats: STR:{profile.strength} INT:{profile.intelligence} CHR:{profile.charisma} END:{profile.endurance} LCK:{profile.luck}
        
        Create an enhanced character profile with:
        1. A cooler, more personalized RPG class name based on their interests
        2. Slight stat adjustments (+1-3 points total) that match their role and interests
        3. A personalized welcome message in character
        
        Return JSON: {{"class": "Enhanced Class Name", "stat_adjustments": {{"strength": 1, "intelligence": 2, ...}}, "message": "personalized welcome"}}
        """
        
        ai_result = generate_ai_response(ai_prompt, max_tokens=600)
        
        try:
            character_data = json.loads(ai_result)
            
            # Update character class if AI provided a better one
            if character_data.get('class'):
                profile.character_class = character_data['class']
            
            # Apply stat adjustments (small bonuses)
            stat_adjustments = character_data.get('stat_adjustments', {})
            for stat, bonus in stat_adjustments.items():
                if hasattr(profile, stat) and isinstance(bonus, int) and 0 <= bonus <= 3:
                    current_value = getattr(profile, stat)
                    setattr(profile, stat, current_value + bonus)
            
            profile.save()
            
            # Update the welcome message
            welcome_msg = character_data.get('message', f'Your character has been enhanced! Welcome, {profile.character_class}!')
            
            # Update or create new AI response
            ai_response, created = AIResponse.objects.get_or_create(
                profile=profile,
                role='assistant',
                defaults={'content': welcome_msg}
            )
            if not created:
                ai_response.content = welcome_msg
                ai_response.timestamp = timezone.now()
                ai_response.save()
                
        except (json.JSONDecodeError, KeyError) as e:
            # If AI response isn't valid JSON, just update the message
            welcome_msg = f"Your {profile.character_class} character has been enhanced! Ready for your adventure?"
            AIResponse.objects.filter(profile=profile, role='assistant').update(
                content=welcome_msg,
                timestamp=timezone.now()
            )
        
        return f"Enhanced character for {profile.name}"
        
    except Profile.DoesNotExist:
        return f"Profile {profile_id} not found"
    except Exception as e:
        return f"Error enhancing character: {str(e)}"


@shared_task  
def generate_ai_quests(profile_id):
    """Background task to generate AI-powered quests after registration"""
    try:
        profile = Profile.objects.get(id=profile_id)
        
        # Remove the basic fallback quests (they have generated_by_ai=False)
        profile.quests.filter(
            completed=False, 
            generated_by_ai=False,
            quest_type='daily'
        ).delete()
        
        # Generate new AI-powered quests
        new_quests = generate_daily_quests(profile, count=5)
        
        return f"Generated {len(new_quests)} AI quests for {profile.name}"
        
    except Profile.DoesNotExist:
        return f"Profile {profile_id} not found"
    except Exception as e:
        return f"Error generating AI quests: {str(e)}"


@shared_task
def refresh_daily_quests_for_all():
    """Background task to refresh daily quests for all active users"""
    from datetime import timedelta
    
    # Get profiles that need new daily quests (last active within 7 days)
    cutoff_date = timezone.now() - timedelta(days=7)
    active_profiles = Profile.objects.filter(last_active__gte=cutoff_date)
    
    quest_count = 0
    for profile in active_profiles:
        # Check if they have uncompleted daily quests
        uncompleted_dailies = profile.quests.filter(
            quest_type='daily',
            completed=False,
            due_date__gte=timezone.now().date()
        ).count()
        
        # If they have fewer than 3 uncompleted daily quests, generate more
        if uncompleted_dailies < 3:
            new_quests = generate_daily_quests(profile, count=3)
            quest_count += len(new_quests)
    
    return f"Generated {quest_count} daily quests for {len(active_profiles)} active profiles" 