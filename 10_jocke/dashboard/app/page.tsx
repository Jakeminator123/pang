"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardPageLayout from "@/components/dashboard/layout";
import DashboardStat from "@/components/dashboard/stat";
import { 
  Building2, 
  Users, 
  FileSpreadsheet, 
  Globe,
  Mail,
  Phone,
  MapPin,
  TrendingUp,
  CheckCircle2,
  Download
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { format } from "date-fns";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface DateFolder {
  date: string;
  formatted: string;
}

interface DateStats {
  totalCompanies: number;
  totalPeople: number;
  hasPeopleData: boolean;
  companiesWithDomain?: number;
  companiesWithEmail?: number;
  companiesWithPhone?: number;
  uniquePeople?: number;
  boardMembers?: number;
  deputies?: number;
  uniqueCities?: number;
  segments?: Record<string, number>;
}

interface DateData {
  date: string;
  stats: DateStats;
}

export default function DashboardOverview() {
  const [dates, setDates] = useState<DateFolder[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [stats, setStats] = useState<DateStats | null>(null);
  const [allDateData, setAllDateData] = useState<DateData[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    fetchDates();
  }, []);

  useEffect(() => {
    if (selectedDate) {
      fetchDateData(selectedDate);
    }
  }, [selectedDate]);

  useEffect(() => {
    if (dates.length > 0) {
      fetchAllDateData();
    }
  }, [dates]);

  const fetchDates = async () => {
    try {
      const response = await fetch("/api/data/dates");
      if (response.ok) {
        const data = await response.json();
        setDates(data.dates);
        if (data.dates.length > 0) {
          setSelectedDate(data.dates[0].date);
        }
      }
    } catch (error) {
      console.error("Error fetching dates:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchDateData = async (date: string) => {
    try {
      const response = await fetch(`/api/data/${date}`);
      if (response.ok) {
        const data = await response.json();
        setStats(data.stats);
      }
    } catch (error) {
      console.error("Error fetching date data:", error);
    }
  };

  const fetchAllDateData = async () => {
    try {
      const promises = dates.slice(0, 10).map(date => 
        fetch(`/api/data/${date.date}`).then(r => r.json())
      );
      const results = await Promise.all(promises);
      setAllDateData(results);
    } catch (error) {
      console.error("Error fetching all date data:", error);
    }
  };

  const handleDateClick = (date: string) => {
    router.push(`/date/${date}`);
  };

  // Prepare chart data from all dates
  const chartData = allDateData
    .sort((a, b) => a.date.localeCompare(b.date))
    .map(data => ({
      date: `${data.date.slice(4, 6)}/${data.date.slice(6, 8)}`,
      companies: data.stats.totalCompanies,
      people: data.stats.totalPeople,
      verified: data.stats.companiesWithDomain || 0,
    }));

  if (loading) {
    return (
      <DashboardPageLayout
        header={{
          title: "Loading...",
          description: "Fetching data",
        }}
      >
        <div className="flex items-center justify-center h-64">
          <div className="text-muted-foreground">Loading...</div>
        </div>
      </DashboardPageLayout>
    );
  }

  return (
    <DashboardPageLayout
      header={{
        title: "Pang Dashboard",
        description: `Last updated: ${new Date().toLocaleString()}`,
      }}
    >
      {/* Main Stats Grid */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          <DashboardStat
            label="TOTAL COMPANIES"
            value={stats.totalCompanies.toString()}
            description="Företag i databasen"
            icon={Building2}
            intent="neutral"
            direction="up"
          />
          <DashboardStat
            label="TOTAL PEOPLE"
            value={stats.totalPeople.toString()}
            description="Styrelsepersoner extraherade"
            icon={Users}
            intent="positive"
            direction="up"
          />
          <DashboardStat
            label="VERIFIED DOMAINS"
            value={stats.companiesWithDomain?.toString() || "0"}
            description={`${stats.companiesWithDomain ? Math.round((stats.companiesWithDomain / stats.totalCompanies) * 100) : 0}% verified`}
            icon={Globe}
            intent={stats.companiesWithDomain && stats.companiesWithDomain > 0 ? "positive" : "neutral"}
            direction="up"
          />
          <DashboardStat
            label="DATA QUALITY"
            value={stats.hasPeopleData ? "Complete" : "Basic"}
            description={stats.hasPeopleData ? "Full parsing done" : "Basic data only"}
            icon={FileSpreadsheet}
            intent={stats.hasPeopleData ? "positive" : "neutral"}
          />
        </div>
      )}

      {/* Secondary Stats */}
      {stats && stats.hasPeopleData && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase">
                Board Members
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.boardMembers || 0}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase">
                Deputies
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.deputies || 0}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase">
                Unique People
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.uniquePeople || 0}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase">
                With Email
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold flex items-center gap-2">
                {stats.companiesWithEmail || 0}
                <Mail className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase">
                With Phone
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold flex items-center gap-2">
                {stats.companiesWithPhone || 0}
                <Phone className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground uppercase">
                Cities
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold flex items-center gap-2">
                {stats.uniqueCities || 0}
                <MapPin className="h-4 w-4 text-muted-foreground" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Chart Section */}
      {chartData.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Trend Analysis</CardTitle>
            <CardDescription>Company and people data over time</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="companies" className="w-full">
              <TabsList>
                <TabsTrigger value="companies">Companies</TabsTrigger>
                <TabsTrigger value="people">People</TabsTrigger>
                <TabsTrigger value="verified">Verified</TabsTrigger>
              </TabsList>
              <TabsContent value="companies" className="mt-4">
                <div className="h-[300px] flex items-center justify-center">
                  <div className="text-center">
                    <TrendingUp className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">
                      Chart visualization coming soon
                    </p>
                    <div className="mt-4 space-y-2">
                      {chartData.map((d, i) => (
                        <div key={i} className="flex justify-between items-center text-sm">
                          <span>{d.date}</span>
                          <Badge>{d.companies} companies</Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </TabsContent>
              <TabsContent value="people" className="mt-4">
                <div className="h-[300px] flex items-center justify-center">
                  <div className="text-center">
                    <Users className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">
                      Chart visualization coming soon
                    </p>
                    <div className="mt-4 space-y-2">
                      {chartData.map((d, i) => (
                        <div key={i} className="flex justify-between items-center text-sm">
                          <span>{d.date}</span>
                          <Badge>{d.people} people</Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </TabsContent>
              <TabsContent value="verified" className="mt-4">
                <div className="h-[300px] flex items-center justify-center">
                  <div className="text-center">
                    <CheckCircle2 className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">
                      Chart visualization coming soon
                    </p>
                    <div className="mt-4 space-y-2">
                      {chartData.map((d, i) => (
                        <div key={i} className="flex justify-between items-center text-sm">
                          <span>{d.date}</span>
                          <Badge>{d.verified} verified</Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      )}

      {/* Segments */}
      {stats && stats.segments && Object.keys(stats.segments).length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Segments</CardTitle>
            <CardDescription>Company distribution by segment</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.segments)
                .sort(([, a], [, b]) => b - a)
                .map(([segment, count]) => (
                  <Badge key={segment} variant="secondary" className="text-sm py-1 px-3">
                    {segment}: {count}
                  </Badge>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Date Folders Grid */}
      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-4">Available Date Folders</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {dates.map((dateFolder) => {
            const dateObj = new Date(
              parseInt(dateFolder.date.slice(0, 4)),
              parseInt(dateFolder.date.slice(4, 6)) - 1,
              parseInt(dateFolder.date.slice(6, 8))
            );

            return (
              <Card
                key={dateFolder.date}
                className={`cursor-pointer transition-all hover:border-primary hover:shadow-lg ${
                  selectedDate === dateFolder.date ? "border-primary border-2" : ""
                }`}
                onClick={() => handleDateClick(dateFolder.date)}
              >
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">
                      {format(dateObj, "PPP")}
                    </CardTitle>
                    <Badge variant="outline">{dateFolder.date}</Badge>
                  </div>
                  <CardDescription>
                    {format(dateObj, "EEEE")}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDateClick(dateFolder.date);
                      }}
                    >
                      View Details →
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        window.location.href = `/api/download/${dateFolder.date}`;
                      }}
                      title="Download ZIP"
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {dates.length === 0 && (
        <Card>
          <CardContent className="pt-6">
            <div className="text-center text-muted-foreground">
              No date folders found. Make sure data exists in 10_jocke/
            </div>
          </CardContent>
        </Card>
      )}
    </DashboardPageLayout>
  );
}
