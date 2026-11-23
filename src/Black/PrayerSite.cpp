#include "PrayerSite.h"
#include "PrayerSiteInfo.h"
#include "PrayerIconInfo.h"
#include "GameTimeConstants.h"
#include "WorshipSpellIcon.h"

inline MESH_LIST GPrayerSiteInfo::GetMesh() const
{
	return Mesh;
}

inline GBaseInfo* GPrayerSiteInfo::GetBaseInfo(uint32_t& info_count)
{
	info_count = ARRAY_SIZE(Infos);
	return Infos;
}

GPrayerSiteInfo GPrayerSiteInfo::Infos[PRAYER_SITE_INFO_LAST];

inline GBaseInfo* GPrayerIconInfo::GetBaseInfo(uint32_t& info_count)
{
	info_count = ARRAY_SIZE(Infos);
	return Infos;
}

GPrayerIconInfo GPrayerIconInfo::Infos[PRAYER_ICON_INFO_LAST];

inline MESH_LIST PrayerSite::GetMesh() const
{
	return info->GetMesh();
}

#ifndef VERSION_BW1W100
#define PRAYER_SITE_DEFAULT_SCALE         0.2f
#define PRAYER_SITE_INITIAL_PERCENT_BUILT 1.0f

PrayerSite::PrayerSite(const MapCoords& coords, const GPrayerSiteInfo* info, float unused_1, float unused_2)
	: MultiMapFixed(coords, info, 0.0f, PRAYER_SITE_DEFAULT_SCALE, PRAYER_SITE_INITIAL_PERCENT_BUILT, false)
{
}
#endif

void PrayerSite::ToBeDeleted(bool32_t delete_now) {}

uint32_t PrayerSite::GetIndexedValue(uint32_t entry_index) const
{
	return IndexedValues.Entries[entry_index];
}

MapCoords PrayerSite::GetPos(uint32_t unused) const
{
	const MapCoords position = Pos;
	return position;
}

uint32_t PrayerSite::Process()
{
	return 3;
}

GPlayer* PrayerSite::GetPlayer()
{
	return NULL;
}

Town* PrayerSite::GetTown()
{
	return MultiMapFixed::GetTown();
}

bool32_t PrayerSite::CreatureMustAvoid(Creature* creature)
{
	return false;
}

#ifndef VERSION_BW1W100
PrayerIcon::PrayerIcon(const MapCoords& coords, const GPrayerIconInfo* info, const GSpellSeedInfo* unused,
                       float y_angle, float scale)
	: SingleMapFixed(coords, info, y_angle, scale), field_0x5c(0)
{
}
#endif

uint32_t PrayerIcon::GetCreatureBeliefType()
{
	return CREATURE_BELIEF_TYPE_MOBILE_OBJECT;
}

#ifndef VERSION_BW1W100
MESH_LIST PrayerIcon::GetMesh() const
{
	return SingleMapFixed::GetMesh();
}
#endif

uint32_t PrayerIcon::Process()
{
	return 3;
}
