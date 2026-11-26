#include "Town.h"
#include <stddef.h> /* For NULL in intrusive-list templates */
#include "GameTimeConstants.h"
#include "Citadel.h"
#include "Game.h"
#include "CitadelInfo.h"
#include "Utils.h"
#include "WorshipSite.h"
#include "WorshipSpellIcon.h"

// BW1W120 00464090 BW1M119 01030680
float Citadel::GetInfluence()
{
	return GGame::g_game->PlayerInfluenceMultiplier * influence;
}

WorshipSite* Citadel::FindOrCreateWorshipSite(const GTribeInfo* tribe_info)
{
	WorshipSite* result = FindTribeWorshipSite(tribe_info);
	if (result == NULL)
	{
		result = RequestANewWorshipSite(tribe_info);
	}
	return result;
}

WorshipSite* Citadel::FindOrCreateWorshipSite(Town* town)
{
	if (town == NULL)
	{
		return NULL;
	}
	WorshipSite* result = NULL;
	if (!CannotBuildWorshipSite && town->IsAllowedToCreateWorshipSite())
	{
		result = FindOrCreateWorshipSite(town->GetTribe());
	}
	return result;
}

uint32_t Citadel::GetSaveType()
{
	return GAME_THING_TYPE_CITADEL;
}

uint32_t Citadel::GetCreatureBeliefType()
{
	return CREATURE_BELIEF_TYPE_CITADEL;
}

uint32_t Citadel::GetCreatureBeliefListType()
{
	return 0;
}

uint32_t Citadel::GetOrigin()
{
	return OBJECT_ORIGIN_MAGIC;
}

bool32_t Citadel::IsSuitableForCreatureActivity()
{
	return true;
}

bool32_t Citadel::IsCitadel()
{
	return true;
}

const char* Citadel::GetText()
{
	return "Citadel";
}

char* Citadel::GetDebugText()
{
	return "Citadel:";
}

GBaseInfo* GCitadelInfo::GetBaseInfo(uint32_t& info_count)
{
	info_count = ARRAY_SIZE(Infos);
	return Infos;
}

WorshipSite* Citadel::FindTribeWorshipSite(const GTribeInfo* tribe_info)
{
	for (unsigned int slot = 0; slot < ARRAY_SIZE(WorshipSites); ++slot)
	{
		WorshipSite* site = WorshipSites[slot];
		if (site != NULL && site->GetTribe() == tribe_info)
		{
			return site;
		}
	}
	return NULL;
}

void Citadel::RemoveWorshipSite(WorshipSite* site)
{
	WorshipSites[site->Slot] = NULL;
}

void Citadel::DrawSpellIcons()
{
	for (unsigned int slot = 0; slot < ARRAY_SIZE(WorshipSites); ++slot)
	{
		WorshipSite* site = WorshipSites[slot];
		if (site != NULL)
		{
			site->DrawSpellIcons();
		}
	}
}

SpellIcon* Citadel::FindSpellIcon(MAGIC_TYPE magic)
{
	for (unsigned int slot = 0; slot < ARRAY_SIZE(WorshipSites); ++slot)
	{
		WorshipSite* site = WorshipSites[slot];
		if (site == NULL)
		{
			continue;
		}
		WorshipSpellIcon* icon = site->GetSpellIconFromMagicType(magic);
		if (icon != NULL)
		{
			return icon;
		}
	}
	return NULL;
}

WorshipSite* Citadel::GetNearestActiveWorshipSite(const MapCoords& coords, float max_distance) const
{
	WorshipSite* nearest_site = NULL;
	for (unsigned int slot = 0; slot < ARRAY_SIZE(WorshipSites); ++slot)
	{
		WorshipSite* site = WorshipSites[slot];
		if (site != NULL && site->GetNumberVillagersWorshipping() != 0)
		{
			MapCoords dance_pos;
			dance_pos.SetToZero();
			site->GetDancePos(&dance_pos);
			float distance = GUtils::GetDistanceInMetres(dance_pos, coords);
			if (distance < max_distance)
			{
				max_distance = distance;
				nearest_site = site;
			}
		}
	}
	return nearest_site;
}

void Citadel::Cheat(int add_spell_icons)
{
	for (unsigned int slot = 0; slot < ARRAY_SIZE(WorshipSites); ++slot)
	{
		WorshipSite* site = WorshipSites[slot];
		if (site != NULL)
		{
			site->Cheat(add_spell_icons);
		}
	}
}
