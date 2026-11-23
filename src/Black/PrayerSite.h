#ifndef BW1_DECOMP_PRAYER_SITE_INCLUDED_H
#define BW1_DECOMP_PRAYER_SITE_INCLUDED_H

#include <assert.h> /* For static_assert */
#include <stdint.h> /* For uint32_t */

#include "MultiMapFixed.h" /* For struct MultiMapFixed */

#define PRAYER_SITE_DEFAULT_SCALE         0.2f
#define PRAYER_SITE_INITIAL_PERCENT_BUILT 1.0f

// Forward Declares

class Base;
class Creature;
class GPlayer;
class GPrayerSiteInfo;
class GameThing;
class Object;
class Town;

class PrayerSite : public MultiMapFixed
{
	struct IndexedValueTable
	{
		uint32_t Entries[4];

		IndexedValueTable()
		{
			Entries[0] = 0;
			Entries[1] = 0;
			Entries[2] = 0;
			Entries[3] = 0;
		}
	};

	IndexedValueTable IndexedValues;
	uint8_t           field_0x8c[4];

public:
	PrayerSite(const MapCoords& coords, const GPrayerSiteInfo* info, float, float);

	using MultiMapFixed::GetPos;
	uint32_t  GetIndexedValue(uint32_t entry_index) const;
	MapCoords GetPos(uint32_t) const;

	// Override methods
	// BW1W120 00670830 BW1M119 inlined
	virtual void ToBeDeleted(bool32_t delete_now);
	// BW1W120 006708c0 BW1M119 inlined
	virtual GPlayer* GetPlayer();
	// BW1W120 006708e0 BW1M119 inlined
	virtual Town* GetTown();
	// BW1W120 006708b0 BW1M119 inlined
	virtual uint32_t Process();
	// BW1W120 006707f0 BW1M119 inlined
	virtual MESH_LIST GetMesh() const;
	// BW1W120 00670a10 BW1M119 inlined
	virtual bool32_t CreatureMustAvoid(Creature* creature);
};

static_assert(sizeof(PrayerSite) == 0x90, "PrayerSite size is incorrect");

#endif /* BW1_DECOMP_PRAYER_SITE_INCLUDED_H */
